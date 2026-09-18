using PhotoAssistant.Application.Storage;
using PhotoAssistant.Domain.Entities;
using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Application.Photos;

/// <summary>What the caller hands over: bytes, a name, and who is uploading.</summary>
public sealed record UploadPhotoRequest
{
    public required Guid UserId { get; init; }

    public required ReadOnlyMemory<byte> Content { get; init; }

    public required string FileName { get; init; }

    public required string ContentType { get; init; }
}

/// <summary>
/// What the screen needs afterwards: the project it should open and the keys to
/// fetch the images by.
/// </summary>
public sealed record UploadPhotoResponse
{
    public required Guid ProjectId { get; init; }

    public required Guid PhotoId { get; init; }

    public required string Name { get; init; }

    public required int Width { get; init; }

    public required int Height { get; init; }
}

/// <summary>
/// Outcome of an upload. A file that is too large or of the wrong kind is an
/// expected answer, not an exception (.claude/rules/backend.md).
/// </summary>
public sealed record UploadPhotoResult
{
    private UploadPhotoResult()
    {
    }

    public bool Succeeded { get; private init; }

    public UploadPhotoResponse? Response { get; private init; }

    public IReadOnlyDictionary<string, string[]> Errors { get; private init; } =
        new Dictionary<string, string[]>();

    public static UploadPhotoResult Success(UploadPhotoResponse response) =>
        new() { Succeeded = true, Response = response };

    public static UploadPhotoResult Failure(string key, params string[] messages) =>
        new()
        {
            Succeeded = false,
            Errors = new Dictionary<string, string[]> { [key] = messages },
        };
}

/// <summary>
/// Receiving a photograph: validate it, derive the two stored sizes, put all
/// three in object storage, and open a project on it.
///
/// <para>
/// **A project is created here, not when a suggestion is chosen.** The editor
/// can be reached without picking one, so the project has to exist before the
/// suggestion screen. The cost is accepted and visible: an abandoned upload
/// leaves a project with no saved version, which the project list shows as an
/// empty state rather than treating as an error.
/// </para>
///
/// <para>
/// **Order matters.** Storage is written before the rows, so a failure leaves
/// objects nothing points at — wasted bytes a cleanup can find. The reverse
/// leaves rows pointing at objects that do not exist, which is a broken screen
/// for the user and a lie in the database.
/// </para>
/// </summary>
public sealed class UploadPhotoHandler(
    IDerivativeGenerator derivatives,
    IObjectStorage storage,
    IPhotoUploadRepository repository,
    TimeProvider clock)
{
    /// <summary>
    /// What a browser may send. An allowlist rather than a blocklist, and it
    /// decides nothing on its own: the ML service decodes the bytes and refuses
    /// anything that is not really an image, so a renamed file fails there.
    /// This exists to reject the obvious case without a round trip.
    /// </summary>
    private static readonly HashSet<string> AcceptedContentTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    };

    /// <summary>
    /// Matches the ML service's own ceiling. Both exist on purpose: this one
    /// avoids sending 60 MB across a network to be refused, and the service's
    /// exists because it must not depend on someone else's validation.
    /// </summary>
    public const int MaximumBytes = 40 * 1024 * 1024;

    public async Task<UploadPhotoResult> UploadAsync(
        UploadPhotoRequest request,
        CancellationToken cancellationToken)
    {
        if (request.Content.IsEmpty)
        {
            return UploadPhotoResult.Failure("file", "The file is empty.");
        }

        if (request.Content.Length > MaximumBytes)
        {
            return UploadPhotoResult.Failure(
                "file",
                $"The file is larger than {MaximumBytes / (1024 * 1024)} MB.");
        }

        if (!AcceptedContentTypes.Contains(request.ContentType))
        {
            return UploadPhotoResult.Failure(
                "file",
                "Only JPEG, PNG and WebP photographs can be uploaded.");
        }

        var derived = await derivatives.DeriveAsync(
            request.Content,
            request.FileName,
            cancellationToken);

        if (!derived.Succeeded)
        {
            return UploadPhotoResult.Failure("file", derived.Error ?? "The file could not be read.");
        }

        var photoId = Guid.CreateVersion7();
        var originalKey = $"uploads/{photoId}/original{ExtensionFor(request.ContentType)}";
        var fitKey = $"uploads/{photoId}/pre512.png";
        var proxyKey = $"uploads/{photoId}/proxy2048.jpg";

        await storage.PutAsync(
            StorageBucket.Originals, originalKey, request.Content, request.ContentType, cancellationToken);
        await storage.PutAsync(
            StorageBucket.Derivatives, fitKey, derived.Fit!.Content, derived.Fit.ContentType, cancellationToken);
        await storage.PutAsync(
            StorageBucket.Derivatives, proxyKey, derived.Proxy!.Content, derived.Proxy.ContentType, cancellationToken);

        var now = clock.GetUtcNow();
        var photo = new Photo
        {
            Id = photoId,
            Source = PhotoSource.User,
            OriginalKey = originalKey,
            Pre512Key = fitKey,
            Proxy2048Key = proxyKey,
            CreatedAt = now,
        };

        var project = new Project
        {
            Id = Guid.CreateVersion7(),
            UserId = request.UserId,
            PhotoId = photo.Id,
            Name = ProjectNameFor(request.FileName),
            CreatedAt = now,
        };

        await repository.SaveAsync(photo, project, cancellationToken);

        return UploadPhotoResult.Success(new UploadPhotoResponse
        {
            ProjectId = project.Id,
            PhotoId = photo.Id,
            Name = project.Name,
            Width = derived.SourceWidth,
            Height = derived.SourceHeight,
        });
    }

    private static string ExtensionFor(string contentType) => contentType.ToLowerInvariant() switch
    {
        "image/png" => ".png",
        "image/webp" => ".webp",
        _ => ".jpg",
    };

    /// <summary>
    /// A first name for the project, from the file name.
    ///
    /// <para>
    /// Derived rather than asked for: a dialog between choosing a photograph and
    /// seeing suggestions interrupts the one thing the person came to do, and the
    /// name can be changed later. The extension goes because "sunset.jpg" is a
    /// file and "sunset" is a project.
    /// </para>
    /// </summary>
    private string ProjectNameFor(string fileName)
    {
        var stem = Path.GetFileNameWithoutExtension(fileName).Trim();

        // A name is not optional, and a browser can send an empty or
        // path-shaped one, so there is always a fallback.
        return stem.Length == 0
            ? $"Untitled {clock.GetUtcNow():yyyy-MM-dd}"
            : stem[..Math.Min(stem.Length, 120)];
    }
}
