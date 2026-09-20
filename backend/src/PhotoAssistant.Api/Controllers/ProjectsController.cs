using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PhotoAssistant.Application.Projects;

namespace PhotoAssistant.Api.Controllers;

/// <summary>
/// Projects. Reading one, for now — the list, renaming and deleting are task 5.
/// </summary>
[ApiController]
[Authorize]
[Route("api/projects")]
public sealed class ProjectsController(GetProjectHandler projects) : ControllerBase
{
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

    private Guid CurrentUserId()
    {
        var value = User.FindFirstValue(ClaimTypes.NameIdentifier);

        return Guid.TryParse(value, out var id)
            ? id
            : throw new InvalidOperationException("The authenticated token carries no user id.");
    }
}
