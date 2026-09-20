namespace PhotoAssistant.Application.Projects;

/// <summary>One project, as a screen needs it.</summary>
public sealed record ProjectSummary
{
    public required Guid Id { get; init; }

    public required string Name { get; init; }

    /// <summary>The photograph it is about. Every image route is addressed by this.</summary>
    public required Guid PhotoId { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }

    /// <summary>How many edits have been saved. Zero for a project nobody finished.</summary>
    public required int VersionCount { get; init; }

    /// <summary>
    /// Whether a suggestion has already been taken or skipped for this
    /// photograph.
    ///
    /// <para>
    /// Reported so the client can stop offering a step that has been passed.
    /// The choice row is the precise signal — a saved version would do only
    /// once the editor saves, and would still miss someone who chose and then
    /// left without saving.
    /// </para>
    /// </summary>
    public required bool HasChoice { get; init; }
}

/// <summary>
/// Reading one project.
///
/// <para>
/// Added here rather than with the rest of the project screens (task 5) because
/// the suggestion screen is reached by project id and needs the photograph
/// behind it. Passing the photograph's id through router state instead would
/// work until someone reloaded the page.
/// </para>
/// </summary>
public sealed class GetProjectHandler(IProjectRepository projects)
{
    public Task<ProjectSummary?> GetAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken) =>
        projects.FindForUserAsync(projectId, userId, cancellationToken);
}
