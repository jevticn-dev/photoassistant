using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Application.Photos;

/// <summary>
/// Persists what an upload creates.
///
/// <para>
/// One method, taking both rows, because they are created by one act and must
/// appear together. A photograph with no project is unreachable — nothing lists
/// it — and a project pointing at a photograph that was never written is a
/// broken screen. Two calls would leave either possible whenever the second
/// fails.
/// </para>
///
/// <para>
/// Named after the act rather than after a table, so the guarantee is stated in
/// the name: this is where an upload becomes durable, not a generic bag of
/// inserts.
/// </para>
/// </summary>
public interface IPhotoUploadRepository
{
    Task SaveAsync(Photo photo, Project project, CancellationToken cancellationToken);
}
