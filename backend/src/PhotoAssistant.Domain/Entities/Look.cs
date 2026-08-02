using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// A named, transferable style. FiveK edits deliberately do not belong here —
/// they are corrections tied to one photograph, not styles you would apply
/// elsewhere.
/// </summary>
public class Look
{
    public Guid Id { get; set; }

    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// The recipe in edit schema v1, as raw JSON. For presets this is a direct
    /// translation rather than a fit — a preset already is a recipe.
    /// TODO (phase 1): replace with the typed EditRecipe model.
    /// </summary>
    public string Edit { get; set; } = string.Empty;

    // As with Example, the style_fingerprint pgvector column lives in the table
    // but not in this model — see LookConfiguration.

    /// <summary>Free-form style grouping, e.g. "warm film". Null until classified.</summary>
    public string? Family { get; set; }

    public LookSource Source { get; set; }

    /// <summary>
    /// Owner for user-imported looks; null for collection presets. A private
    /// look is visible only to its owner until they choose to share it.
    /// </summary>
    public Guid? OwnerUserId { get; set; }

    public DateTimeOffset CreatedAt { get; set; }
}
