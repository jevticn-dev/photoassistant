using System.ComponentModel.DataAnnotations;
using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
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
    DeleteProjectHandler delete) : ControllerBase
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
