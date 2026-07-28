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
    /// TODO (phase 1): replace with the typed EditRecipe model.
    /// </summary>
    public string Edit { get; set; } = string.Empty;

    public DateTimeOffset CreatedAt { get; set; }
}
