using System.Text.Json;
using System.Text.Json.Serialization;

namespace PhotoAssistant.Application.Exports;

/// <summary>
/// What a queued export carries, as it is written into <c>jobs.payload</c>.
///
/// <para>
/// <b>The recipe travels with the job rather than being looked up.</b> The
/// worker renders what the person was looking at when they asked, which is not
/// necessarily the newest saved version — asking for an export does not save
/// one, because a version is a turning point somebody meant to keep and an
/// export is not (§B111). It also keeps the worker ignorant of projects and
/// versions: it renders an object with a recipe, and that is all it needs to be
/// told.
/// </para>
///
/// <para>
/// The property names are the ones the Python side reads, so they are written
/// in camelCase explicitly rather than left to whatever the serialiser happens
/// to be configured with. A rename on either side is a broken job, and jobs
/// fail in the background where nobody is looking.
/// </para>
/// </summary>
public sealed record ExportPayload
{
    [JsonPropertyName("projectId")]
    public required Guid ProjectId { get; init; }

    /// <summary>The untouched upload, which is the only thing at full size.</summary>
    [JsonPropertyName("originalKey")]
    public required string OriginalKey { get; init; }

    /// <summary>The recipe in canonical form, exactly as a version would store it.</summary>
    [JsonPropertyName("recipe")]
    public required JsonElement Recipe { get; init; }
}

/// <summary>What the worker wrote when it finished, read back out of <c>jobs.result</c>.</summary>
public sealed record ExportResult
{
    [JsonPropertyName("key")]
    public required string Key { get; init; }

    [JsonPropertyName("contentType")]
    public required string ContentType { get; init; }

    [JsonPropertyName("width")]
    public required int Width { get; init; }

    [JsonPropertyName("height")]
    public required int Height { get; init; }

    [JsonPropertyName("bytes")]
    public required long Bytes { get; init; }
}

/// <summary>
/// Where a job has got to, as the screen watching it needs to know.
/// </summary>
public sealed record JobState
{
    public required Guid Id { get; init; }

    /// <summary><c>pending</c>, <c>running</c>, <c>done</c> or <c>failed</c>.</summary>
    public required string Status { get; init; }

    public required DateTimeOffset CreatedAt { get; init; }

    public required DateTimeOffset UpdatedAt { get; init; }

    /// <summary>
    /// What went wrong, when something did. The worker's own sentence rather
    /// than an exception's: it is written to be shown.
    /// </summary>
    public required string? Error { get; init; }

    /// <summary>The finished file's size and dimensions, once there is one.</summary>
    public required ExportResult? Result { get; init; }

    /// <summary>
    /// The recipe this export rendered, in edit schema v1.
    ///
    /// <para>
    /// Carried so the editor can tell whether the file still matches what is on
    /// screen. Without it the download button offers the last export whatever
    /// has happened since, which after one slider movement is a button offering
    /// a different photograph than the one being looked at.
    /// </para>
    ///
    /// <para>
    /// Comparing recipes rather than versions on purpose: an export is not tied
    /// to a version (§B118), and an edit changed but not saved is still an edit
    /// the file does not match.
    /// </para>
    /// </summary>
    public required JsonElement? Edit { get; init; }
}
