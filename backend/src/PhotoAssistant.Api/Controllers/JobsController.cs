using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PhotoAssistant.Application.Exports;

namespace PhotoAssistant.Api.Controllers;

/// <summary>
/// Background work: how it is going, and its file once it is done.
///
/// <para>
/// Only exports today, which is the only kind of job a person can ask for. A
/// job that is not this user's is absent rather than forbidden, like everything
/// else here addressed by an identifier.
/// </para>
/// </summary>
[ApiController]
[Authorize]
[Route("api/jobs")]
public sealed class JobsController(GetJobHandler jobs) : ControllerBase
{
    /// <summary>Where an export has got to. The screen asks this while it waits.</summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType<JobState>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Get(Guid id, CancellationToken cancellationToken)
    {
        var job = await jobs.GetAsync(id, CurrentUserId(), cancellationToken);

        return job is null ? NotFound() : Ok(job);
    }

    /// <summary>The finished export.</summary>
    /// <remarks>
    /// Through the API rather than from storage directly (ADR-15). A job that
    /// is not finished yet answers 404 rather than a status: a download is a
    /// file or it is nothing, and the screen already knows how to ask whether
    /// there is one.
    /// </remarks>
    [HttpGet("{id:guid}/download")]
    [Produces("image/png")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Download(Guid id, CancellationToken cancellationToken)
    {
        var file = await jobs.DownloadAsync(id, CurrentUserId(), cancellationToken);

        if (file is null)
        {
            return NotFound();
        }

        // Named so the browser saves it rather than shows it, and named after
        // the job so two exports of one project do not overwrite each other in
        // somebody's downloads folder.
        return File(file.Content.ToArray(), file.ContentType, $"photoassistant-{id}.png");
    }

    private Guid CurrentUserId()
    {
        var value = User.FindFirstValue(ClaimTypes.NameIdentifier);

        return Guid.TryParse(value, out var id)
            ? id
            : throw new InvalidOperationException("The authenticated token carries no user id.");
    }
}
