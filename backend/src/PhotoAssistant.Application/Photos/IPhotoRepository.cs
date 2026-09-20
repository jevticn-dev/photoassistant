using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Application.Photos;

/// <summary>Reading photographs back, with ownership already applied.</summary>
public interface IPhotoRepository
{
    /// <summary>
    /// The photograph, if this user may see it. Null otherwise — and null for
    /// both cases, "no such photograph" and "someone else's", on purpose.
    ///
    /// <para>
    /// A photograph carries no owner of its own; a project does. Access
    /// therefore means "this user has a project on it", which is also what
    /// makes sharing possible later without changing this shape.
    /// </para>
    /// </summary>
    Task<Photo?> FindForUserAsync(Guid photoId, Guid userId, CancellationToken cancellationToken);
}
