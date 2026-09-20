using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using PhotoAssistant.Application.Photos;

namespace PhotoAssistant.Infrastructure.MlService;

/// <summary>
/// <c>POST /recommend</c> on the ML service, behind the Application interface.
///
/// <para>
/// The second call across this boundary, after derivation. The boundary itself
/// does not move: the service publishes no port and nginx proxies only
/// <c>/api/</c> and <c>/health</c>, so this is reached by its compose name on
/// the private network and by nothing from a browser.
/// </para>
/// </summary>
internal sealed class MlRecommendationService(
    HttpClient client,
    ILogger<MlRecommendationService> logger) : IRecommendationService
{
    /// <summary>The service is Python and answers in snake_case. See the derivation client.</summary>
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<RecommendationResult> SuggestAsync(
        ReadOnlyMemory<byte> image,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        using var file = new ByteArrayContent(image.ToArray());
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");

        // The field name is the contract: the route declares `image: UploadFile`
        // and FastAPI binds by name.
        content.Add(file, "image", "photo.png");

        HttpResponseMessage response;
        try
        {
            response = await client.PostAsync("/recommend", content, cancellationToken);
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            logger.LogError(error, "The ML service did not answer the recommendation request");

            return RecommendationResult.Failure(
                "Suggestions are unavailable right now. Try again in a moment.");
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                logger.LogError(
                    "The ML service answered {StatusCode} to a recommendation request",
                    (int)response.StatusCode);

                return RecommendationResult.Failure(
                    "Suggestions are unavailable right now. Try again in a moment.");
            }

            var body = await response.Content.ReadFromJsonAsync<RecommendResponse>(
                Json, cancellationToken);

            if (body is null || body.Suggestions.Count == 0)
            {
                // An empty list is not a valid answer: the pool is 25.000 edits
                // and the strategy always returns three. Nothing means the
                // corpus is missing or the query never ran, and showing an empty
                // screen would present that as "no ideas for this photograph".
                logger.LogError("The ML service returned no suggestions");

                return RecommendationResult.Failure(
                    "Suggestions are unavailable right now. Try again in a moment.");
            }

            return RecommendationResult.Success(
                body.Suggestions.Select(ToSuggestion).ToArray(),
                body.PoolSize,
                body.Neighbours);
        }
    }

    private static Suggestion ToSuggestion(SuggestionBody body) => new()
    {
        Recipe = body.Recipe,
        SourceReference = body.SourceReference,
        Expert = body.Expert,
        SceneDistance = body.SceneDistance,
    };

    private sealed record RecommendResponse(
        IReadOnlyList<SuggestionBody> Suggestions,
        int PoolSize,
        int Neighbours);

    private sealed record SuggestionBody(
        // The recipe travels as an opaque document. The API neither reads nor
        // validates it: the schema lives in three languages already, and a
        // fourth opinion here would be a fourth thing to keep in step. It is
        // stored as written and handed to the editor, which does understand it.
        IReadOnlyDictionary<string, object?> Recipe,
        string SourceReference,
        string? Expert,
        double SceneDistance);
}
