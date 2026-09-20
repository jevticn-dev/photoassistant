namespace PhotoAssistant.Application.Projects;

/// <summary>Reading projects, with ownership already applied.</summary>
public interface IProjectRepository
{
    /// <summary>The project, if it is this user's. Null for both "no such" and "not yours".</summary>
    Task<ProjectSummary?> FindForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken);
}
