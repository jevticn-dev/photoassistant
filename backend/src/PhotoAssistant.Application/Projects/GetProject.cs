using System.Text.Json;
using PhotoAssistant.Application.Photos;

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

    /// <summary>
    /// The recipe the editor opens on, in edit schema v1, or null when there is
    /// nothing to open on and the editor starts from the photograph unchanged.
    ///
    /// <para>
    /// A <see cref="JsonElement"/> rather than a string, so that it arrives as
    /// an object on the wire instead of a document escaped inside another one.
    /// Handed over as it was stored rather than parsed on the way out. The C#
    /// model exists — it is one of the three the schema is maintained in — but
    /// reading a version costs nothing to validate again: it was validated
    /// before it was written, which is where an invalid document can still be
    /// refused rather than merely reported.
    /// </para>
    /// </summary>
    public required JsonElement? StartingEdit { get; init; }
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
    public async Task<ProjectSummary?> GetAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var project = await projects.FindForUserAsync(projectId, userId, cancellationToken);

        if (project is null)
        {
            return null;
        }

        return new ProjectSummary
        {
            Id = project.Id,
            Name = project.Name,
            PhotoId = project.PhotoId,
            CreatedAt = project.CreatedAt,
            VersionCount = project.VersionCount,

            // A choice log exists exactly when the screen has been passed, so
            // the flag is that fact rather than a second query asking it again.
            HasChoice = project.LatestChoiceLog is not null,
            StartingEdit = StartingEdit(project),
        };
    }

    /// <summary>
    /// Where the editor picks up: the last thing saved, else what was chosen,
    /// else nothing.
    ///
    /// <para>
    /// The order is the point. A saved version is the person's own work and
    /// outranks the suggestion it grew out of; the suggestion outranks the
    /// untouched photograph. Reading it from the server rather than carrying it
    /// through router state is what makes the editor survive a reload, which is
    /// the same reason this endpoint exists at all.
    /// </para>
    /// </summary>
    private static JsonElement? StartingEdit(ProjectRecord project)
    {
        if (project.LatestVersionEdit is { } saved)
        {
            return Parse(saved);
        }

        return project.LatestChoiceLog is { } log
            ? ChoiceLog.ReadChosenRecipe(log)
            : null;
    }

    /// <summary>
    /// Both columns are <c>jsonb</c>, so the database has already refused
    /// anything that is not JSON and this cannot throw. What it has not
    /// checked is whether the JSON is a <em>recipe</em>: `{"schema": 99}` is
    /// valid jsonb and nonsense to the editor. That check belongs to the
    /// client, which owns a model of the schema and refuses what it cannot
    /// apply; handing the document over unread keeps one validator rather
    /// than two that can disagree.
    /// </summary>
    private static JsonElement Parse(string document)
    {
        using var parsed = JsonDocument.Parse(document);

        // Cloned, because the element is only valid while its document is.
        return parsed.RootElement.Clone();
    }
}
