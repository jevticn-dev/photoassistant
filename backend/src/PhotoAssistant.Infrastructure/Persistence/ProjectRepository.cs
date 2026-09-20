using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Application.Projects;

namespace PhotoAssistant.Infrastructure.Persistence;

internal sealed class ProjectRepository(PhotoAssistantDbContext context) : IProjectRepository
{
    public Task<ProjectRecord?> FindForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken) =>
        context.Projects
            // Ownership is in the query, not a check after it.
            .Where(project => project.Id == projectId && project.UserId == userId)
            .Select(project => new ProjectRecord
            {
                Id = project.Id,
                Name = project.Name,
                PhotoId = project.PhotoId,
                CreatedAt = project.CreatedAt,
                VersionCount = project.Versions.Count,

                // Both are the newest of their kind, and both come back as the
                // stored document. Ordering by CreatedAt rather than by id: the
                // ids are version 7 GUIDs and therefore already time-ordered,
                // but that is a property of how they happen to be generated,
                // not something a query should depend on.
                LatestVersionEdit = project.Versions
                    .OrderByDescending(version => version.CreatedAt)
                    .Select(version => version.Edit)
                    .FirstOrDefault(),
                LatestChoiceLog = context.Choices
                    .Where(choice =>
                        choice.PhotoId == project.PhotoId && choice.UserId == project.UserId)
                    .OrderByDescending(choice => choice.CreatedAt)
                    .Select(choice => choice.ShownSuggestions)
                    .FirstOrDefault(),
            })
            .AsNoTracking()
            .SingleOrDefaultAsync(cancellationToken);
}
