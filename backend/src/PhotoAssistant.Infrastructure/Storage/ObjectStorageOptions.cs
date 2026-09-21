namespace PhotoAssistant.Infrastructure.Storage;

/// <summary>
/// Where objects go, read from configuration. No value has a default: a bucket
/// name guessed in code would create a second, empty one on first write and the
/// mistake would look like data loss.
/// </summary>
public sealed class ObjectStorageOptions
{
    public required string Endpoint { get; init; }

    public required string AccessKey { get; init; }

    public required string SecretKey { get; init; }

    /// <summary>
    /// S3 requires one; MinIO ignores it. Kept configurable because a move to
    /// R2 or B2 (ADR-12, ADR-15) makes it matter again.
    /// </summary>
    public required string Region { get; init; }

    public required string OriginalsBucket { get; init; }

    public required string DerivativesBucket { get; init; }

    public required string ExportsBucket { get; init; }
}
