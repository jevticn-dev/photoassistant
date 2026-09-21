using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.Extensions.Logging;
using PhotoAssistant.Application.Photos;

namespace PhotoAssistant.Infrastructure.MlService;

/// <summary>
/// Asks the ML service for the two stored sizes (ADR-27).
///
/// <para>
/// The first connection between the API and the ML service. The boundary does
/// not move because of it: the service stays without a published port, nginx
/// still proxies only <c>/api</c> and <c>/health</c>, and it is reached by its
/// compose name on the private network.
/// </para>
/// </summary>
internal sealed class MlDerivativeGenerator(
    HttpClient client,
    ILogger<MlDerivativeGenerator> logger) : IDerivativeGenerator
{
    /// <summary>
    /// The service is Python and answers in snake_case (<c>content_type</c>,
    /// <c>source_width</c>). The web defaults would look for camelCase, find
    /// nothing, and hand back a record of zeroes and nulls — a wrong answer
    /// rather than an error, which is why this is stated rather than left to a
    /// default.
    /// </summary>
    private static readonly System.Text.Json.JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<DerivativeResult> DeriveAsync(
        ReadOnlyMemory<byte> image,
        string fileName,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        using var file = new ByteArrayContent(image.ToArray());
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");

        // The field name is part of the contract: the route declares
        // `image: UploadFile`, and FastAPI matches by name, not by position.
        content.Add(file, "image", fileName);

        HttpResponseMessage response;
        try
        {
            response = await client.PostAsync("/derivatives", content, cancellationToken);
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            // The service being down is our problem, not the uploader's, so the
            // detail goes to the log and the person gets something actionable.
            logger.LogError(error, "The ML service did not answer the derivative request");

            return DerivativeResult.Failure(
                "The photograph could not be processed right now. Try again in a moment.");
        }

        using (response)
        {
            if (response.StatusCode is HttpStatusCode.BadRequest or HttpStatusCode.RequestEntityTooLarge)
            {
                // The service decoded the bytes and refused them. That verdict
                // is about the file, so it belongs to the uploader.
                var problem = await ReadProblemAsync(response, cancellationToken);

                return DerivativeResult.Failure(problem ?? "The file could not be read as an image.");
            }

            if (!response.IsSuccessStatusCode)
            {
                logger.LogError(
                    "The ML service answered {StatusCode} to a derivative request",
                    (int)response.StatusCode);

                return DerivativeResult.Failure(
                    "The photograph could not be processed right now. Try again in a moment.");
            }

            var body = await response.Content.ReadFromJsonAsync<DerivativesResponse>(Json, cancellationToken);

            if (body is null)
            {
                logger.LogError("The ML service answered with a body that could not be read");

                return DerivativeResult.Failure(
                    "The photograph could not be processed right now. Try again in a moment.");
            }

            return DerivativeResult.Success(
                body.Fit.ToDerived(),
                body.Proxy.ToDerived(),
                body.SourceWidth,
                body.SourceHeight);
        }
    }

    private static async Task<string?> ReadProblemAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var problem = await response.Content.ReadFromJsonAsync<FastApiError>(Json, cancellationToken);

            return problem?.Detail;
        }
        catch (Exception error) when (error is HttpRequestException or NotSupportedException or System.Text.Json.JsonException)
        {
            // A refusal we cannot parse is still a refusal; the caller has a
            // fallback message.
            return null;
        }
    }

    /// <summary>FastAPI's shape for an HTTPException, which is not RFC 9457.</summary>
    private sealed record FastApiError(string? Detail);

    private sealed record DerivativesResponse(
        EncodedImage Fit,
        EncodedImage Proxy,
        int SourceWidth,
        int SourceHeight);

    private sealed record EncodedImage(string Data, string ContentType, int Width, int Height)
    {
        public DerivedImage ToDerived() => new()
        {
            Content = Convert.FromBase64String(Data),
            ContentType = ContentType,
            Width = Width,
            Height = Height,
        };
    }
}
