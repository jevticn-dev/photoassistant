namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// Evidence that a particular edit was applied to a particular photograph.
/// This is what the recommender searches: "what did experts do to scenes like
/// this one".
/// </summary>
public class Example
{
    public Guid Id { get; set; }

    public Guid PhotoId { get; set; }
    public Photo Photo { get; set; } = null!;

    /// <summary>
    /// Set only when the edit came from a named look. Null for FiveK edits —
    /// those are corrections, not transferable styles.
    /// </summary>
    public Guid? LookId { get; set; }
    public Look? Look { get; set; }

    /// <summary>
    /// The fitted recipe in edit schema v1, as raw JSON.
    /// TODO (phase 1): replace with the typed EditRecipe model; the column type
    /// stays jsonb, so this is a mapping change and not a migration.
    /// </summary>
    public string Edit { get; set; } = string.Empty;

    /// <summary>FiveK expert who produced the edit: "A" to "E". Null otherwise.</summary>
    public string? Expert { get; set; }

    /// <summary>
    /// Mean colour difference left over after fitting, measured between the
    /// rendered recipe and the expert's TIFF. Reported rather than hidden —
    /// its distribution is one of the evaluation metrics.
    /// <para>
    /// Null when the edit was never fitted, which is the case for every row
    /// flagged by <see cref="ExcludedFromFitting"/>. Null rather than a
    /// sentinel: zero would read as a perfect reconstruction and put those rows
    /// at the top of "best fitted examples", while any impossible value is an
    /// exception every future query has to remember. Null drops out of
    /// comparisons on its own.
    /// </para>
    /// </summary>
    public double? FitError { get; set; }

    // The table also carries style_fingerprint, a pgvector column describing the
    // "after" image (colour statistics combined with a DINOv2 embedding) and used
    // for diversity selection. Written by the pipeline, read by the ML service,
    // never touched from .NET — see ExampleConfiguration.

    /// <summary>Object key of the 512px "after" image.</summary>
    public string? AfterKey { get; set; }

    /// <summary>
    /// Set when the source edit used grayscale conversion or local adjustments,
    /// which edit schema v1 does not model. Flagged rows are excluded from
    /// fitting.
    /// </summary>
    public bool ExcludedFromFitting { get; set; }

    /// <summary>
    /// Why the edit was excluded: "grayscale", "local", "crop" or "rotated".
    /// Null for rows that were fitted.
    /// <para>
    /// Kept in the table rather than only in the pipeline's staging file because
    /// the phase gate asks the database how many edits were excluded
    /// <em>and for what</em>, and an answer that requires a file on somebody's
    /// disk is not an answer the database can give.
    /// </para>
    /// </summary>
    public string? ExcludedReason { get; set; }

    public DateTimeOffset CreatedAt { get; set; }
}
