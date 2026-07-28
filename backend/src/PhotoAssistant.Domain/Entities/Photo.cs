using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// One physical photograph. For FiveK this is 5.000 rows, not 25.000 — the
/// expert edits of the same photograph are <see cref="Example"/> rows.
/// </summary>
public class Photo
{
    public Guid Id { get; set; }

    public PhotoSource Source { get; set; }

    /// <summary>
    /// Object key of the untouched upload. Null for FiveK photos: their raw DNG
    /// stays in the read-only dataset folder and is never copied into storage.
    /// </summary>
    public string? OriginalKey { get; set; }

    /// <summary>512px "before" image — the fitting and fingerprint resolution.</summary>
    public string? Pre512Key { get; set; }

    /// <summary>2048px JPEG the editor renders its live preview from.</summary>
    public string? Proxy2048Key { get; set; }

    // The table also carries clip_embedding, a pgvector column holding the CLIP
    // embedding of the "before" image. It is absent from this model on purpose:
    // the pipeline writes it and the ML service searches it, while the .NET side
    // never reads or sets it. See PhotoConfiguration.

    /// <summary>
    /// Semantic labels as key/value pairs (scene, light, subject), filtered from
    /// the catalogue keywords. Raw JSON — no typed model until it is needed.
    /// </summary>
    public string? Tags { get; set; }

    /// <summary>
    /// Identifier of the photo in its source dataset, e.g. "a0042". Null for
    /// user uploads. Lets the pipeline recognise what it has already ingested.
    /// </summary>
    public string? SourceReference { get; set; }

    public DateTimeOffset CreatedAt { get; set; }

    public ICollection<Example> Examples { get; set; } = [];
}
