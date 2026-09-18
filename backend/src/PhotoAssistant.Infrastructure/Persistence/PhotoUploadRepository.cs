using PhotoAssistant.Application.Photos;
using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Infrastructure.Persistence;

/// <summary>
/// Writes the photograph and the project it starts, in one transaction.
///
/// <para>
/// One <c>SaveChangesAsync</c> is the transaction: EF wraps a single save in
/// one, so the two rows either both appear or neither does. Splitting them
/// across two saves would need an explicit transaction to keep the same
/// guarantee, and would invite someone to remove it later as ceremony.
/// </para>
/// </summary>
internal sealed class PhotoUploadRepository(PhotoAssistantDbContext context) : IPhotoUploadRepository
{
    public async Task SaveAsync(Photo photo, Project project, CancellationToken cancellationToken)
    {
        context.Photos.Add(photo);
        context.Projects.Add(project);

        await context.SaveChangesAsync(cancellationToken);
    }
}
