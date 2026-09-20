namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// One saved state of a project. Each row is a complete recipe, not a delta
/// (ADR-6): a recipe is about a kilobyte, so deltas would save nothing while
/// turning "restore this version" into a replay that one bad delta can corrupt.
/// </summary>
public class EditVersion
{
    public Guid Id { get; set; }

    public Guid ProjectId { get; set; }
    public Project Project { get; set; } = null!;

    /// <summary>
    /// Full recipe snapshot in edit schema v1, as raw JSON.
    ///
    /// <para>
    /// A string on purpose, although <see cref="Edits.EditRecipe"/> exists and
    /// is what validates every document on its way into this column. The column
    /// is <c>jsonb</c> and what it holds is the canonical form of a schema kept
    /// in three languages; binding it to the C# model would make a row readable
    /// only by whichever version of that model is compiled in, and `schema: 1`
    /// has to stay readable for good.
    /// </para>
    /// </summary>
    public string Edit { get; set; } = string.Empty;

    public DateTimeOffset CreatedAt { get; set; }
}
