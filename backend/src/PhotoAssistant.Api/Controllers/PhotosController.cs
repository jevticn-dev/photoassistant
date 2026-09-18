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
public sealed class PhotosController(UploadPhotoHandler upload) : ControllerBase
{
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
