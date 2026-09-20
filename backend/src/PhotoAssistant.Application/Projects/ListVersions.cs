using System.Text.Json;

namespace PhotoAssistant.Application.Projects;

/// <summary>One version as it is stored, before it is given its place.</summary>
public sealed record StoredVersion
{
    public required Guid Id { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }

    /// <summary>The recipe, as the column holds it.</summary>
    public required string Edit { get; init; }
}

/// <summary>
/// One entry in a project's history.
///
/// <para>
/// It carries the recipe, which the project list deliberately does not do for
/// its own rows. The difference is what the list is for: a list of projects
/// exists to be chosen from, and the documents behind it would be sent so that
/// none of them could be shown. A history exists to be looked through — every
/// entry is one click away from being the thing on screen, and a click that
/// waits for the network is not a history that anyone scrubs through.
/// </para>
/// </summary>
public sealed record VersionEntry
{
    public required Guid Id { get; init; }

    /// <summary><c>V01</c>, <c>V02</c>… — the position, computed rather than stored (§B116).</summary>
    public required string Label { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }

    /// <summary>
    /// The full recipe this version saved, in edit schema v1.
    ///
    /// <para>
    /// Handed over as it was stored, for the reason
    /// <see cref="ProjectSummary.StartingEdit"/> gives: it was validated on the
    /// way in, which is the last moment an invalid document could be refused
    /// rather than merely reported, and the client owns a model of the schema
    /// that refuses what it cannot apply.
    /// </para>
    /// </summary>
    public required JsonElement Edit { get; init; }
}

/// <summary>
/// A project's history, oldest first.
///
/// <para>
/// <b>Oldest first, because the labels are positions.</b> <c>V01</c> is the
/// first thing saved and stays <c>V01</c> forever; a list that put the newest
/// at the top would number itself backwards or renumber as it grew. It is also
/// how the strip in the editor reads — downwards, in the order the work
/// happened.
/// </para>
///
/// <para>
/// <b>There is no route for going back to one.</b> Restoring a version means
/// saving its recipe again, which is <see cref="SaveVersionHandler"/> and
/// nothing more: history only ever grows, so "restore V01" can only mean "put
/// V01 back on top". That is not a shortcut — it is what makes "restoring does
/// not delete anything newer" a property of the shape rather than a rule
/// somebody has to keep (§B118).
/// </para>
/// </summary>
public sealed class ListVersionsHandler(IProjectRepository projects)
{
    /// <summary>The history, or null when there is no such project of this user's.</summary>
    public async Task<IReadOnlyList<VersionEntry>?> ListAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var stored = await projects.ListVersionsForUserAsync(projectId, userId, cancellationToken);

        if (stored is null)
        {
            return null;
        }

        // The label is the position in this list, which is why the ordering the
        // repository applies is part of the contract rather than a convenience.
        return [.. stored.Select((version, index) => new VersionEntry
        {
            Id = version.Id,
            Label = $"V{index + 1:D2}",
            CreatedAt = version.CreatedAt,
            Edit = Parse(version.Edit),
        })];
    }

    /// <summary>
    /// The column is <c>jsonb</c>, so this cannot throw on anything the
    /// database accepted. What it does not promise is that the JSON is a
    /// recipe, and that check belongs to the client for the reason
    /// <see cref="GetProjectHandler"/> gives.
    /// </summary>
    private static JsonElement Parse(string document)
    {
        using var parsed = JsonDocument.Parse(document);

        // Cloned, because the element is only valid while its document is.
        return parsed.RootElement.Clone();
    }
}
