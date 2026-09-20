using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Application.Projects;
using PhotoAssistant.Domain.Entities;
using PhotoAssistant.Domain.Enums;

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

    public async Task<IReadOnlyList<ProjectListItem>> ListForUserAsync(
        Guid userId,
        CancellationToken cancellationToken) =>
        await context.Projects
            .Where(project => project.UserId == userId)
            .Select(project => new ProjectListItem
            {
                Id = project.Id,
                Name = project.Name,
                PhotoId = project.PhotoId,
                VersionCount = project.Versions.Count,

                // A project with no version falls back to when it was created,
                // which is a normal state rather than a gap: the upload makes
                // the project, so leaving before saving leaves exactly this.
                LastEditedAt = project.Versions
                    .Max(version => (DateTimeOffset?)version.CreatedAt) ?? project.CreatedAt,
            })
            .OrderByDescending(project => project.LastEditedAt)
            .AsNoTracking()
            .ToListAsync(cancellationToken);

    public async Task<bool> RenameForUserAsync(
        Guid projectId,
        Guid userId,
        string name,
        CancellationToken cancellationToken)
    {
        // One statement, no round trip to load first. The ownership predicate
        // is part of it, so a project that is not this user's updates nothing
        // and the count says so.
        var updated = await context.Projects
            .Where(project => project.Id == projectId && project.UserId == userId)
            .ExecuteUpdateAsync(
                setters => setters.SetProperty(project => project.Name, name),
                cancellationToken);

        return updated > 0;
    }

    public async Task<SavedVersion?> AddVersionForUserAsync(
        Guid projectId,
        Guid userId,
        string edit,
        DateTimeOffset at,
        CancellationToken cancellationToken)
    {
        // Ownership first, and as a query rather than a load: nothing about the
        // project itself is needed to append to it.
        var owns = await context.Projects.AnyAsync(
            project => project.Id == projectId && project.UserId == userId,
            cancellationToken);

        if (!owns)
        {
            return null;
        }

        var version = new EditVersion
        {
            Id = Guid.CreateVersion7(),
            ProjectId = projectId,
            Edit = edit,
            CreatedAt = at,
        };

        context.EditVersions.Add(version);
        await context.SaveChangesAsync(cancellationToken);

        // Counted after the insert, so the new row is included and the label is
        // the position this version actually holds.
        var position = await context.EditVersions.CountAsync(
            row => row.ProjectId == projectId, cancellationToken);

        return new SavedVersion
        {
            Id = version.Id,
            Label = $"V{position:D2}",
            CreatedAt = version.CreatedAt,
        };
    }

    public async Task<DeletedObjects?> DeleteForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var project = await context.Projects
            .Include(candidate => candidate.Photo)
            .Where(candidate => candidate.Id == projectId && candidate.UserId == userId)
            .SingleOrDefaultAsync(cancellationToken);

        if (project is null)
        {
            return null;
        }

        var photo = project.Photo;

        // Two conditions, and both matter. A corpus photograph is shared by
        // 25.000 fitted examples and must never be touched by anything a user
        // does; and a photograph another project still points at is not this
        // project's to remove, even though nothing creates that case today.
        var sharedWithAnother = await context.Projects.AnyAsync(
            other => other.PhotoId == project.PhotoId && other.Id != project.Id,
            cancellationToken);

        var removePhoto = photo.Source == PhotoSource.User && !sharedWithAnother;

        if (removePhoto)
        {
            // The choice rows name the photograph by foreign key, and that key
            // is Restrict rather than Cascade, so they are removed explicitly
            // rather than left for the database to complain about.
            var choices = await context.Choices
                .Where(choice => choice.PhotoId == photo.Id)
                .ToListAsync(cancellationToken);

            context.Choices.RemoveRange(choices);
        }

        // The versions go with the project through the cascade the schema
        // declares; only the project itself is removed here.
        context.Projects.Remove(project);

        if (removePhoto)
        {
            context.Photos.Remove(photo);
        }

        await context.SaveChangesAsync(cancellationToken);

        return new DeletedObjects
        {
            OriginalKey = removePhoto ? photo.OriginalKey : null,
            DerivativeKeys = removePhoto
                ? new[] { photo.Pre512Key, photo.Proxy2048Key }.OfType<string>().ToList()
                : [],
        };
    }
}
