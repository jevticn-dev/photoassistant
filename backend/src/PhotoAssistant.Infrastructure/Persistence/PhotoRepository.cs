using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence;

internal sealed class PhotoRepository(PhotoAssistantDbContext context) : IPhotoRepository
{
    public Task<Photo?> FindForUserAsync(
        Guid photoId,
        Guid userId,
        CancellationToken cancellationToken) =>
        context.Photos
            // Ownership is part of the query, not a check after it. Fetching
            // first and comparing afterwards is the shape that eventually grows
            // a path where someone forgets the second half.
            .Where(photo => photo.Id == photoId)
            .Where(photo => context.Projects
                .Any(project => project.PhotoId == photo.Id && project.UserId == userId))
            .AsNoTracking()
            .SingleOrDefaultAsync(cancellationToken);
}
