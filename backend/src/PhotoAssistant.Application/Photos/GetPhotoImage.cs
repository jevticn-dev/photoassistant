using PhotoAssistant.Application.Storage;

namespace PhotoAssistant.Application.Photos;

/// <summary>Which stored size is being asked for.</summary>
public enum PhotoImageKind
{
    /// <summary>2048px JPEG — what the editor renders from.</summary>
    Proxy,

    /// <summary>512px PNG — what search runs on. Served for diagnostics, not for display.</summary>
    Fit,
}

/// <summary>
/// Serving a stored image to the browser.
///
/// <para>
/// Through the API rather than from MinIO directly, which ADR-15 requires:
/// object storage is not reachable from the internet, and ownership is checked
/// here. A presigned URL would move both of those out of the application.
/// </para>
/// </summary>
public sealed class GetPhotoImageHandler(IPhotoRepository photos, IObjectStorage storage)
{
    public async Task<StoredObject?> GetAsync(
        Guid photoId,
        Guid userId,
        PhotoImageKind kind,
        CancellationToken cancellationToken)
    {
        var photo = await photos.FindForUserAsync(photoId, userId, cancellationToken);

        var key = kind switch
        {
            PhotoImageKind.Proxy => photo?.Proxy2048Key,
            PhotoImageKind.Fit => photo?.Pre512Key,
            _ => null,
        };

        // Null covers all three of: no such photograph, not this user's, and a
        // row without that derivative. The caller answers 404 to each, because
        // distinguishing them tells a stranger which identifiers are real.
        return key is null
            ? null
            : await storage.GetAsync(StorageBucket.Derivatives, key, cancellationToken);
    }
}
