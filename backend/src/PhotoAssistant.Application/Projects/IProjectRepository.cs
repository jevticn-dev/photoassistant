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

/// <summary>Reading projects, with ownership already applied.</summary>
public interface IProjectRepository
{
    /// <summary>The project, if it is this user's. Null for both "no such" and "not yours".</summary>
    Task<ProjectRecord?> FindForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken);
}
