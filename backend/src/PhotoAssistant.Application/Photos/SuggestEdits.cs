using PhotoAssistant.Application.Storage;

namespace PhotoAssistant.Application.Photos;

/// <summary>What the suggestion screen receives.</summary>
public sealed record SuggestEditsResponse
{
    public required IReadOnlyList<Suggestion> Suggestions { get; init; }

    /// <summary>Candidate edits the search considered. Shown to nobody; useful in a log.</summary>
    public required int PoolSize { get; init; }
}

/// <summary>
/// Outcome. "No such photograph" and "not yours" are the same answer, and the
/// service being unreachable is a third — all of them expected enough to be
/// returned rather than thrown (.claude/rules/backend.md).
/// </summary>
public sealed record SuggestEditsResult
{
    private SuggestEditsResult()
    {
    }

    public bool Succeeded { get; private init; }

    public SuggestEditsResponse? Response { get; private init; }

    public bool NotFound { get; private init; }

    public string? Error { get; private init; }

    public static SuggestEditsResult Success(SuggestEditsResponse response) =>
        new() { Succeeded = true, Response = response };

    public static SuggestEditsResult Missing() => new() { NotFound = true };

    public static SuggestEditsResult Failure(string error) => new() { Error = error };
}

/// <summary>
/// Three edit suggestions for a photograph the user owns.
///
/// <para>
/// <b>The 512px derivative is what gets sent, not the original.</b> Three
/// reasons, in order of weight. It is the size the corpus vectors were computed
/// at, produced by the same code (ADR-27), so the comparison is like for like.
/// It is 170 KB against 15 MB, over a hop that happens on every upload. And the
/// ML service would resize the original to exactly this anyway, so sending the
/// large one buys a slower request and an extra resample.
/// </para>
/// </summary>
public sealed class SuggestEditsHandler(
    IPhotoRepository photos,
    IObjectStorage storage,
    IRecommendationService recommendations)
{
    public async Task<SuggestEditsResult> SuggestAsync(
        Guid photoId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var photo = await photos.FindForUserAsync(photoId, userId, cancellationToken);

        // Missing and forbidden answer alike: telling someone their guess named
        // a real photograph is itself information.
        if (photo?.Pre512Key is null)
        {
            return SuggestEditsResult.Missing();
        }

        var image = await storage.GetAsync(
            StorageBucket.Derivatives, photo.Pre512Key, cancellationToken);

        if (image is null)
        {
            // A row pointing at an object that is not there. The upload writes
            // storage before the rows precisely so this cannot happen, so it
            // means something outside the application removed it.
            return SuggestEditsResult.Failure(
                "The photograph could not be read. Try uploading it again.");
        }

        var result = await recommendations.SuggestAsync(image.Content, cancellationToken);

        if (!result.Succeeded)
        {
            return SuggestEditsResult.Failure(
                result.Error ?? "Suggestions are unavailable right now.");
        }

        return SuggestEditsResult.Success(new SuggestEditsResponse
        {
            Suggestions = result.Suggestions,
            PoolSize = result.PoolSize,
        });
    }
}
