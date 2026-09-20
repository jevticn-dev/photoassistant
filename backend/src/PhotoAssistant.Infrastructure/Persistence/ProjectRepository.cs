using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Application.Projects;

namespace PhotoAssistant.Infrastructure.Persistence;

internal sealed class ProjectRepository(PhotoAssistantDbContext context) : IProjectRepository
{
    public Task<ProjectSummary?> FindForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken) =>
        context.Projects
            // Ownership is in the query, not a check after it.
            .Where(project => project.Id == projectId && project.UserId == userId)
            .Select(project => new ProjectSummary
            {
                Id = project.Id,
                Name = project.Name,
                PhotoId = project.PhotoId,
                CreatedAt = project.CreatedAt,
                VersionCount = project.Versions.Count,
                HasChoice = context.Choices.Any(choice =>
                    choice.PhotoId == project.PhotoId && choice.UserId == project.UserId),
            })
            .AsNoTracking()
            .SingleOrDefaultAsync(cancellationToken);
}
