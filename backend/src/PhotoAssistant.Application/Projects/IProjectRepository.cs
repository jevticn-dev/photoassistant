namespace PhotoAssistant.Application.Projects;

/// <summary>
/// One project as it is stored, before anything is made of it.
///
/// <para>
/// The two edit documents come back as raw JSON rather than as a parsed recipe:
/// deciding which one the editor opens on is a rule, and a rule belongs in the
/// handler rather than in a query.
/// </para>
/// </summary>
public sealed record ProjectRecord
{
    public required Guid Id { get; init; }

    public required string Name { get; init; }

    public required Guid PhotoId { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }

    public required int VersionCount { get; init; }

    /// <summary>The most recently saved version's recipe, if anything is saved.</summary>
    public required string? LatestVersionEdit { get; init; }

    /// <summary>
    /// The most recent choice log for this photograph, if the person has been
    /// past the suggestion screen. Its shape is <see cref="Photos.ChoiceLog"/>.
    /// </summary>
    public required string? LatestChoiceLog { get; init; }
}

/// <summary>
/// Projects, with ownership already applied.
///
/// <para>
/// Every method takes the user id and folds it into the query rather than
/// checking afterwards. That is the shape that cannot grow a path where the
/// second half is forgotten — and it is why someone else's project answers
/// "no such project" rather than "not yours", which would confirm that the
/// identifier names something real.
/// </para>
/// </summary>
public interface IProjectRepository
{
    /// <summary>The project, if it is this user's. Null for both "no such" and "not yours".</summary>
    Task<ProjectRecord?> FindForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken);

    /// <summary>This user's projects, most recently edited first.</summary>
    Task<IReadOnlyList<ProjectListItem>> ListForUserAsync(
        Guid userId,
        CancellationToken cancellationToken);

    /// <summary>True when a project of this user's was renamed.</summary>
    Task<bool> RenameForUserAsync(
        Guid projectId,
        Guid userId,
        string name,
        CancellationToken cancellationToken);

    /// <summary>
    /// Appends a version to a project of this user's and returns it with the
    /// label its position earns. Null when there is no such project.
    /// </summary>
    Task<SavedVersion?> AddVersionForUserAsync(
        Guid projectId,
        Guid userId,
        string edit,
        DateTimeOffset at,
        CancellationToken cancellationToken);

    /// <summary>
    /// Removes the project, its versions, and the photograph it was about when
    /// nothing else needs it. Returns the objects left for storage to clear,
    /// or null when there was no such project of this user's.
    /// </summary>
    Task<DeletedObjects?> DeleteForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken);
}
