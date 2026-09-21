using PhotoAssistant.Domain.Edits;

namespace PhotoAssistant.Application.Projects;

/// <summary>One saved version, as the editor needs it back.</summary>
public sealed record SavedVersion
{
    public required Guid Id { get; init; }

    /// <summary>
    /// <c>V01</c>, <c>V02</c>… — the position in this project's history.
    ///
    /// <para>
    /// Computed from the order rather than stored. A label that is a column has
    /// to be kept in step with the rows it labels, and the only thing it would
    /// add is the ability to be wrong. Versions are never deleted, so counting
    /// is not a guess.
    /// </para>
    /// </summary>
    public required string Label { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }
}

public sealed record SaveVersionResult
{
    private SaveVersionResult()
    {
    }

    public bool Succeeded { get; private init; }

    public bool NotFound { get; private init; }

    public string? Error { get; private init; }

    public SavedVersion? Version { get; private init; }

    public static SaveVersionResult Success(SavedVersion version) =>
        new() { Succeeded = true, Version = version };

    public static SaveVersionResult Missing() => new() { NotFound = true };

    public static SaveVersionResult Invalid(string error) => new() { Error = error };
}

/// <summary>
/// Writing one version of a project's edit.
///
/// <para>
/// <b>A full snapshot, not a delta</b> (ADR-6). A recipe is about a kilobyte,
/// so deltas would save nothing worth having while turning "restore this
/// version" from reading one row into replaying a chain that one bad link
/// corrupts for everything after it.
/// </para>
///
/// <para>
/// <b>Validated here, and stored in canonical form.</b> The column is
/// <c>jsonb</c>, so the database already refuses anything that is not JSON —
/// but it has no idea what a recipe is, and `{"nonsense": true}` is valid jsonb
/// (§B107). <see cref="EditRecipe.FromJson"/> is the C# side of the schema that
/// is maintained in three languages and proven equal over
/// <c>fixtures/edits/</c>, so the check here is the same check the renderer and
/// the pipeline apply. What is written back is <see cref="EditRecipe.ToJson"/>
/// rather than the bytes that arrived: every key present, in schema order, so
/// what a version means does not depend on which client wrote it.
/// </para>
/// </summary>
public sealed class SaveVersionHandler(IProjectRepository projects, TimeProvider clock)
{
    public async Task<SaveVersionResult> SaveAsync(
        Guid projectId,
        Guid userId,
        string document,
        CancellationToken cancellationToken)
    {
        EditRecipe recipe;

        try
        {
            recipe = EditRecipe.FromJson(document);
        }
        catch (EditSchemaException error)
        {
            // The message names the field and the rule it broke, and it is ours
            // rather than a parser's, so it is safe to show.
            return SaveVersionResult.Invalid(error.Message);
        }

        var saved = await projects.AddVersionForUserAsync(
            projectId,
            userId,
            recipe.ToJson(),
            clock.GetUtcNow(),
            cancellationToken);

        return saved is null
            ? SaveVersionResult.Missing()
            : SaveVersionResult.Success(saved);
    }
}
