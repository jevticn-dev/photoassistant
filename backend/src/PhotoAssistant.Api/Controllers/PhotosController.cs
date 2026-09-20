using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using PhotoAssistant.Application.Photos;

namespace PhotoAssistant.Api.Controllers;

/// <summary>
/// Uploading a photograph, which also opens a project on it.
/// </summary>
/// <remarks>
/// The controller does three things and no more: it reads the request, calls
/// the use case, and maps the result. Storage, HTTP to the ML service and the
/// database are reached through interfaces the Application layer declares, and
/// <c>ControllerDependencyTests</c> fails the build if any of them appears in
/// this constructor.
/// </remarks>
[ApiController]
[Authorize]
[Route("api/photos")]
public sealed class PhotosController(
    UploadPhotoHandler upload,
    SuggestEditsHandler suggestions,
    GetPhotoImageHandler images,
    RecordChoiceHandler choices) : ControllerBase
{
    /// <summary>The 2048px working copy the editor renders from.</summary>
    /// <remarks>
    /// Served through the API rather than from a presigned storage URL: MinIO
    /// is not reachable from the internet (ADR-15), and ownership is decided
    /// here. It costs a proxy hop for an image that is fetched once per
    /// editing session.
    /// </remarks>
    [HttpGet("{id:guid}/proxy")]
    [Produces("image/jpeg")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public Task<IActionResult> Proxy(Guid id, CancellationToken cancellationToken) =>
        ImageAsync(id, PhotoImageKind.Proxy, cancellationToken);

    /// <summary>The 512px copy, small enough for a list of projects.</summary>
    /// <remarks>
    /// The same image the search runs on, because it is the only small one
    /// stored. It is a lossless PNG made for fitting rather than for looking
    /// at, so it is about the size of the 2048px JPEG beside it — acceptable
    /// for a handful of cards, and the thing to fix first if a list ever grows
    /// long enough to feel it.
    /// </remarks>
    [HttpGet("{id:guid}/thumbnail")]
    [Produces("image/png")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public Task<IActionResult> Thumbnail(Guid id, CancellationToken cancellationToken) =>
        ImageAsync(id, PhotoImageKind.Fit, cancellationToken);

    private async Task<IActionResult> ImageAsync(
        Guid id,
        PhotoImageKind kind,
        CancellationToken cancellationToken)
    {
        var image = await images.GetAsync(id, CurrentUserId(), kind, cancellationToken);

        if (image is null)
        {
            return NotFound();
        }

        // A derivative never changes: the key contains the photograph's id and
        // the bytes behind it are written once. Immutable lets the browser
        // re-open the editor without asking again, and `private` keeps it out
        // of any shared cache, because this one belongs to one person.
        Response.Headers.CacheControl = "private, max-age=31536000, immutable";

        return File(image.Content.ToArray(), image.ContentType);
    }

    /// <summary>Records which of the three suggestions was taken, if any.</summary>
    [HttpPost("{id:guid}/choices")]
    [ProducesResponseType<RecordChoiceResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> RecordChoice(
        Guid id,
        RecordChoiceBody body,
        CancellationToken cancellationToken)
    {
        var result = await choices.RecordAsync(
            new RecordChoiceRequest
            {
                PhotoId = id,
                UserId = CurrentUserId(),
                Shown = body.Shown,
                ChosenIndex = body.ChosenIndex,
            },
            cancellationToken);

        if (result.NotFound)
        {
            return NotFound();
        }

        if (!result.Succeeded)
        {
            return ValidationProblem(Problem("shown", result.Error!));
        }

        return CreatedAtAction(
            actionName: nameof(RecordChoice),
            routeValues: new { id },
            value: new RecordChoiceResponse { ChoiceId = result.ChoiceId });
    }

    /// <summary>What the client sends when a suggestion is taken or skipped.</summary>
    public sealed record RecordChoiceBody
    {
        /// <summary>All three, as they were shown.</summary>
        public required IReadOnlyList<Suggestion> Shown { get; init; }

        /// <summary>Which one was taken, or null for none.</summary>
        public int? ChosenIndex { get; init; }
    }

    public sealed record RecordChoiceResponse
    {
        public required Guid ChoiceId { get; init; }
    }

    /// <summary>Three stylistically different edits for a photograph.</summary>
    /// <remarks>
    /// POST rather than GET: the work behind it is a CLIP encode and a vector
    /// search, and the answer is not a resource sitting at an address. It is
    /// also where the choice will be logged from (task 3).
    /// </remarks>
    [HttpPost("{id:guid}/recommendations")]
    [ProducesResponseType<SuggestEditsResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> Recommendations(Guid id, CancellationToken cancellationToken)
    {
        var result = await suggestions.SuggestAsync(id, CurrentUserId(), cancellationToken);

        if (result.NotFound)
        {
            // 404 for someone else's photograph too, not 403: a 403 confirms
            // that the identifier names something real.
            return Problem(
                title: "Not found",
                detail: "No such photograph.",
                statusCode: StatusCodes.Status404NotFound);
        }

        if (!result.Succeeded)
        {
            // The service being unavailable is our failure, and 503 says so —
            // it also tells a client that retrying is the sensible response,
            // which a 500 does not.
            return Problem(
                title: "Suggestions unavailable",
                detail: result.Error,
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        return Ok(result.Response);
    }

    /// <summary>Uploads a photograph and starts a project on it.</summary>
    [HttpPost]
    [ProducesResponseType<UploadPhotoResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    // Multipart, because the alternative is base64 in JSON, which costs a third
    // more bytes on something already measured in megabytes.
    [RequestSizeLimit(UploadPhotoHandler.MaximumBytes)]
    public async Task<IActionResult> Upload(IFormFile file, CancellationToken cancellationToken)
    {
        if (file is null)
        {
            return ValidationProblem(Problem("file", "No file was sent."));
        }

        // Read once into memory. A photograph is tens of megabytes at most and
        // both the ML service and object storage need the whole thing, so
        // streaming would buy nothing and complicate both.
        using var buffer = new MemoryStream();
        await file.CopyToAsync(buffer, cancellationToken);

        var result = await upload.UploadAsync(
            new UploadPhotoRequest
            {
                UserId = CurrentUserId(),
                Content = buffer.ToArray(),
                FileName = file.FileName,
                ContentType = file.ContentType,
            },
            cancellationToken);

        if (!result.Succeeded)
        {
            return ValidationProblem(ToModelState(result));
        }

        // 201 with the project it created: the client's next move is to open
        // that project, so it is a new resource rather than an acknowledgement.
        return CreatedAtAction(
            actionName: nameof(Upload),
            routeValues: new { id = result.Response!.PhotoId },
            value: result.Response);
    }

    /// <summary>
    /// The signed-in user, from the token rather than from the request body.
    /// Taking it from the body would let anyone upload into anyone's account.
    /// </summary>
    private Guid CurrentUserId()
    {
        var value = User.FindFirstValue(ClaimTypes.NameIdentifier);

        // [Authorize] has already run, so a request without a usable subject is
        // a bug in token issuing, not a request to be handled politely.
        return Guid.TryParse(value, out var id)
            ? id
            : throw new InvalidOperationException("The authenticated token carries no user id.");
    }

    private static ModelStateDictionary Problem(string field, string message)
    {
        var state = new ModelStateDictionary();
        state.AddModelError(field, message);

        return state;
    }

    private static ModelStateDictionary ToModelState(UploadPhotoResult result)
    {
        var state = new ModelStateDictionary();

        foreach (var (field, messages) in result.Errors)
        {
            foreach (var message in messages)
            {
                state.AddModelError(field, message);
            }
        }

        return state;
    }
}
