using System.ComponentModel.DataAnnotations;
using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using PhotoAssistant.Application.Exports;
using PhotoAssistant.Application.Projects;

namespace PhotoAssistant.Api.Controllers;

/// <summary>
/// Projects: the list, one of them, renaming and deleting.
///
/// <para>
/// Ownership is part of every query rather than a check around it, so a project
/// belonging to someone else is absent rather than forbidden. A 403 would
/// confirm that the identifier names something real, which is a fact the person
/// asking has no business learning.
/// </para>
/// </summary>
[ApiController]
[Authorize]
[Route("api/projects")]
public sealed class ProjectsController(
    ListProjectsHandler list,
    GetProjectHandler projects,
    RenameProjectHandler rename,
    DeleteProjectHandler delete,
    SaveVersionHandler versions,
    ListVersionsHandler history,
    RequestExportHandler exports,
    ListExportsHandler exportHistory) : ControllerBase
{
    /// <summary>Everything this person is working on, most recently edited first.</summary>
    [HttpGet]
    [ProducesResponseType<IReadOnlyList<ProjectListItem>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public async Task<IActionResult> List(CancellationToken cancellationToken) =>
        Ok(await list.ListAsync(CurrentUserId(), cancellationToken));

    /// <summary>One project, with the photograph it is about.</summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType<ProjectSummary>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Get(Guid id, CancellationToken cancellationToken)
    {
        var project = await projects.GetAsync(id, CurrentUserId(), cancellationToken);

        // Someone else's project is absent, not forbidden — the same rule the
        // photograph routes follow.
        return project is null ? NotFound() : Ok(project);
    }

    /// <summary>Renames a project. The only thing about one that is editable.</summary>
    [HttpPatch("{id:guid}")]
    [ProducesResponseType<RenameProjectResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Rename(
        Guid id,
        RenameProjectBody body,
        CancellationToken cancellationToken)
    {
        var result = await rename.RenameAsync(id, CurrentUserId(), body.Name, cancellationToken);

        if (result.NotFound)
        {
            return NotFound();
        }

        if (!result.Succeeded)
        {
            return ValidationProblem(Problem(nameof(body.Name), result.Error!));
        }

        return Ok(new RenameProjectResponse { Name = result.Name! });
    }

    /// <summary>
    /// Deletes a project, and with it the photograph it was about.
    /// </summary>
    /// <remarks>
    /// Not reversible, and it takes the uploaded file with it: an upload makes
    /// exactly one project, so keeping the photograph would leave on the server
    /// the very file the person asked to be rid of. The client confirms before
    /// calling this.
    /// </remarks>
    [HttpDelete("{id:guid}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Delete(Guid id, CancellationToken cancellationToken) =>
        await delete.DeleteAsync(id, CurrentUserId(), cancellationToken)
            ? NoContent()
            : NotFound();

    /// <summary>Saves the edit as it stands, as a full snapshot of the recipe.</summary>
    /// <remarks>
    /// The body is the recipe document itself rather than a wrapper around it:
    /// what is being stored is exactly what the renderer applies, and a field
    /// named "edit" holding it would be one more shape that the three language
    /// models would have to agree about.
    /// </remarks>
    [HttpPost("{id:guid}/versions")]
    [ProducesResponseType<SavedVersion>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> SaveVersion(
        Guid id,
        [FromBody] JsonElement body,
        CancellationToken cancellationToken)
    {
        var result = await versions.SaveAsync(
            id, CurrentUserId(), body.GetRawText(), cancellationToken);

        if (result.NotFound)
        {
            return NotFound();
        }

        if (!result.Succeeded)
        {
            return ValidationProblem(Problem("edit", result.Error!));
        }

        return CreatedAtAction(
            actionName: nameof(Get),
            routeValues: new { id },
            value: result.Version);
    }

    /// <summary>Everything that has been saved for this project, oldest first.</summary>
    /// <remarks>
    /// There is no companion route for restoring one. Putting an old version
    /// back on top is a save of its recipe, which is the route above — history
    /// only grows, so that is the only thing "restore" can mean here (§B118).
    /// </remarks>
    [HttpGet("{id:guid}/versions")]
    [ProducesResponseType<IReadOnlyList<VersionEntry>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Versions(Guid id, CancellationToken cancellationToken)
    {
        var listed = await history.ListAsync(id, CurrentUserId(), cancellationToken);

        // Null is "no such project of yours"; an empty list is a project nobody
        // has saved anything in, which is an ordinary state (decision G).
        return listed is null ? NotFound() : Ok(listed);
    }

    /// <summary>Queues the photograph at full size, with this edit applied.</summary>
    /// <remarks>
    /// The body is the recipe, exactly as saving a version takes it — what is
    /// exported is what is on screen, which is not necessarily the newest saved
    /// version. Asking for a file does not make a version: a version is a
    /// turning point somebody meant to keep, and an export is not one.
    ///
    /// <para>
    /// 202 rather than 201: nothing has been made yet. The job id is how the
    /// screen follows it, through <c>GET /api/jobs/{id}</c>.
    /// </para>
    /// </remarks>
    [HttpPost("{id:guid}/export")]
    [ProducesResponseType<ExportQueuedResponse>(StatusCodes.Status202Accepted)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Export(
        Guid id,
        [FromBody] JsonElement body,
        CancellationToken cancellationToken)
    {
        var result = await exports.RequestAsync(
            id, CurrentUserId(), body.GetRawText(), cancellationToken);

        if (result.NotFound)
        {
            return NotFound();
        }

        if (!result.Succeeded)
        {
            return ValidationProblem(Problem("edit", result.Error!));
        }

        return Accepted(new ExportQueuedResponse { JobId = result.JobId });
    }

    /// <summary>Every export asked for on this project, newest first.</summary>
    /// <remarks>
    /// The editor reads the first entry when it opens, so a finished file is
    /// still reachable after a reload — without it the export exists on the
    /// server with no way to it through the application, which is what somebody
    /// meets after closing the tab on a render they were waiting for.
    /// </remarks>
    [HttpGet("{id:guid}/exports")]
    [ProducesResponseType<IReadOnlyList<JobState>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> Exports(Guid id, CancellationToken cancellationToken)
    {
        var listed = await exportHistory.ListAsync(id, CurrentUserId(), cancellationToken);

        return listed is null ? NotFound() : Ok(listed);
    }

    /// <summary>The job to follow. Nothing exists at a URL yet, which is why this is not a location.</summary>
    public sealed record ExportQueuedResponse
    {
        public required Guid JobId { get; init; }
    }

    /// <summary>The new name. Absent or blank is a 400, not a project called nothing.</summary>
    public sealed record RenameProjectBody
    {
        [Required]
        public required string Name { get; init; }
    }

    public sealed record RenameProjectResponse
    {
        public required string Name { get; init; }
    }

    private static ModelStateDictionary Problem(string field, string message)
    {
        var state = new ModelStateDictionary();
        state.AddModelError(field, message);

        return state;
    }

    private Guid CurrentUserId()
    {
        var value = User.FindFirstValue(ClaimTypes.NameIdentifier);

        return Guid.TryParse(value, out var id)
            ? id
            : throw new InvalidOperationException("The authenticated token carries no user id.");
    }
}
