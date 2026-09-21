namespace PhotoAssistant.Application.Photos;

/// <summary>
/// Produces the two stored sizes of an uploaded photograph.
///
/// <para>
/// Implemented by a call to the ML service rather than in .NET, and that is a
/// decision rather than convenience (ADR-27). The 512px derivative is the input
/// to a comparison against 25.000 corpus images, and those were produced by the
/// Python imaging code: area-averaged in linear light, to an exact size, with
/// JPEG chroma left at full resolution. Resize an upload any other way and it
/// stops being the same kind of image as the corpus it is matched against —
/// nothing fails, the search just returns slightly different neighbours.
/// </para>
/// </summary>
public interface IDerivativeGenerator
{
    /// <summary>
    /// Derives both sizes, or explains why the bytes could not be used.
    /// </summary>
    Task<DerivativeResult> DeriveAsync(
        ReadOnlyMemory<byte> image,
        string fileName,
        CancellationToken cancellationToken);
}

/// <summary>One derived image, as it arrives back from the service.</summary>
public sealed record DerivedImage
{
    public required ReadOnlyMemory<byte> Content { get; init; }

    public required string ContentType { get; init; }

    public required int Width { get; init; }

    public required int Height { get; init; }
}

/// <summary>
/// The outcome of deriving. A file the service cannot decode is an expected
/// answer to a user's upload, not a fault, so it is returned rather than thrown
/// (.claude/rules/backend.md).
/// </summary>
public sealed record DerivativeResult
{
    private DerivativeResult()
    {
    }

    public bool Succeeded { get; private init; }

    public DerivedImage? Fit { get; private init; }

    public DerivedImage? Proxy { get; private init; }

    public int SourceWidth { get; private init; }

    public int SourceHeight { get; private init; }

    /// <summary>Why it failed, in words meant for the person who uploaded.</summary>
    public string? Error { get; private init; }

    public static DerivativeResult Success(
        DerivedImage fit,
        DerivedImage proxy,
        int sourceWidth,
        int sourceHeight) => new()
        {
            Succeeded = true,
            Fit = fit,
            Proxy = proxy,
            SourceWidth = sourceWidth,
            SourceHeight = sourceHeight,
        };

    public static DerivativeResult Failure(string error) =>
        new() { Succeeded = false, Error = error };
}
