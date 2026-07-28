using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// Pipeline manifest: one row per (photo, step). Restarting the pipeline skips
/// whatever is already <see cref="JobStatus.Done"/>, which is what makes every
/// step idempotent and the whole run resumable.
/// </summary>
public class IngestStatus
{
    /// <summary>
    /// Dataset identifier of the photo, e.g. "a0042".
    ///
    /// Deliberately not a foreign key to <see cref="Photo"/>: the first pipeline
    /// step parses the catalogue before any photo row exists, so the manifest
    /// has to be able to record progress for something the database does not
    /// know about yet.
    /// </summary>
    public string PhotoReference { get; set; } = string.Empty;

    /// <summary>
    /// Pipeline step name, e.g. "decode_dng". Kept as text rather than an enum
    /// because the step list belongs to the pipeline and will grow with new
    /// adapters.
    /// </summary>
    public string Step { get; set; } = string.Empty;

    public JobStatus Status { get; set; }

    /// <summary>Failure detail for the last attempt, if it failed.</summary>
    public string? Error { get; set; }

    public DateTimeOffset UpdatedAt { get; set; }
}
