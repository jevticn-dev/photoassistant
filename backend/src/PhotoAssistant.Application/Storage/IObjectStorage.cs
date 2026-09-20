namespace PhotoAssistant.Application.Storage;

/// <summary>
/// Where binary content lives. Implemented against S3 (MinIO locally, ADR-12
/// and ADR-15); nothing above this interface knows that.
/// </summary>
public interface IObjectStorage
{
    /// <summary>
    /// Writes an object and returns the key it was written under.
    /// </summary>
    /// <remarks>
    /// The key is passed in rather than generated here. Keys are part of the
    /// data model — they end up in <c>photos.original_key</c> and are how the
    /// pipeline's own objects are addressed — so deciding them inside a storage
    /// adapter would put a naming convention where nobody looks for it.
    /// </remarks>
    Task<string> PutAsync(
        StorageBucket bucket,
        string key,
        ReadOnlyMemory<byte> content,
        string contentType,
        CancellationToken cancellationToken);

    /// <summary>
    /// Reads an object back. Returns null when the key does not exist, because
    /// a missing derivative is a state the caller has to handle rather than an
    /// exceptional one — an interrupted upload can leave exactly that.
    /// </summary>
    Task<StoredObject?> GetAsync(
        StorageBucket bucket,
        string key,
        CancellationToken cancellationToken);

    /// <summary>
    /// Removes an object. A key that is not there is not an error: deleting is
    /// how a caller says "this must not exist", and it already does not.
    /// </summary>
    Task DeleteAsync(
        StorageBucket bucket,
        string key,
        CancellationToken cancellationToken);
}

/// <summary>
/// The three buckets the project uses, named by purpose rather than by their
/// configured names. What each is actually called comes from configuration, so
/// a deployment can rename them without touching code.
/// </summary>
public enum StorageBucket
{
    /// <summary>Untouched uploads. Never served directly; the export path reads them.</summary>
    Originals,

    /// <summary>The 512px and 2048px derivatives, and anything else derived.</summary>
    Derivatives,

    /// <summary>Finished full-resolution exports, written by the job worker.</summary>
    Exports,
}

/// <summary>One object as it came back out of storage.</summary>
public sealed record StoredObject
{
    public required ReadOnlyMemory<byte> Content { get; init; }

    public required string ContentType { get; init; }
}
