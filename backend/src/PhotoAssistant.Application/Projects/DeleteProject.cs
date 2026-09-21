using PhotoAssistant.Application.Storage;

namespace PhotoAssistant.Application.Projects;

/// <summary>
/// What a delete left behind for storage to clear up.
///
/// <para>
/// Keys rather than a photograph: by the time this comes back the rows are
/// gone, and what remains is a list of objects nothing points at any more.
/// </para>
/// </summary>
public sealed record DeletedObjects
{
    public required string? OriginalKey { get; init; }

    public required IReadOnlyList<string> DerivativeKeys { get; init; }
}

/// <summary>
/// Deleting a project, and with it the photograph it was about.
///
/// <para>
/// <b>The photograph goes too.</b> An upload creates exactly one project
/// (decision G), so the two are one thing to the person who made them; a delete
/// that kept the photograph would leave the file they asked to be rid of on the
/// server while telling them it was gone. Two conditions keep that from
/// reaching anything else: the photograph must have come from a user, never
/// from the corpus, and no other project may still refer to it.
/// </para>
///
/// <para>
/// The choice log goes with it. That log is a quality metric and eventually
/// training data (plan §1.1), so losing it costs something real — but it names
/// the photograph by foreign key, and keeping rows that point at a photograph
/// somebody asked to have removed is the worse of the two.
/// </para>
/// </summary>
public sealed class DeleteProjectHandler(IProjectRepository projects, IObjectStorage storage)
{
    public async Task<bool> DeleteAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        // The database first, storage second, and the order is not arbitrary.
        // If storage fails afterwards the objects leak, which costs disk and
        // nothing else. The other way round leaves rows pointing at objects
        // that are gone, and every screen reading them breaks.
        var deleted = await projects.DeleteForUserAsync(projectId, userId, cancellationToken);

        if (deleted is null)
        {
            return false;
        }

        if (deleted.OriginalKey is { } original)
        {
            await storage.DeleteAsync(StorageBucket.Originals, original, cancellationToken);
        }

        foreach (var key in deleted.DerivativeKeys)
        {
            await storage.DeleteAsync(StorageBucket.Derivatives, key, cancellationToken);
        }

        return true;
    }
}
