namespace PhotoAssistant.Application.Photos;

/// <summary>
/// Asks the ML service for three edit suggestions.
///
/// <para>
/// The API is the only public door: the browser never reaches the ML service,
/// which publishes no port (`.claude/rules/ml_service.md`). This is the bridge
/// plan §9 describes, and the reason the route exists at all — the suggestions
/// themselves are computed behind it.
/// </para>
/// </summary>
public interface IRecommendationService
{
    Task<RecommendationResult> SuggestAsync(
        ReadOnlyMemory<byte> image,
        CancellationToken cancellationToken);
}

/// <summary>
/// One suggestion: an edit, and where it came from.
///
/// <para>
/// No rendered image (phase 4, decision C). The browser runs the same renderer,
/// proven equal to the Python one by the golden test, over the 2048px proxy it
/// loads for the editor anyway — so it draws the previews itself, at the
/// resolution the person is about to work at rather than a smaller one.
/// </para>
/// </summary>
public sealed record Suggestion
{
    /// <summary>The edit in schema v1 — what the editor applies.</summary>
    public required IReadOnlyDictionary<string, object?> Recipe { get; init; }

    /// <summary>
    /// The FiveK photograph the edit was taken from. Diagnostic, not for
    /// display: nobody outside this project knows what a0002-dgw_005 is.
    /// </summary>
    public required string SourceReference { get; init; }

    /// <summary>Which of the five experts made it, a to e.</summary>
    public required string? Expert { get; init; }

    /// <summary>Cosine distance from the upload to that scene.</summary>
    public required double SceneDistance { get; init; }
}

/// <summary>
/// The outcome. A service that is down is our fault rather than the caller's,
/// but it is still an answer the route has to give rather than an exception to
/// let escape (.claude/rules/backend.md).
/// </summary>
public sealed record RecommendationResult
{
    private RecommendationResult()
    {
    }

    public bool Succeeded { get; private init; }

    public IReadOnlyList<Suggestion> Suggestions { get; private init; } = [];

    /// <summary>Candidate edits considered before choosing. Reported for the log.</summary>
    public int PoolSize { get; private init; }

    /// <summary>Similar photographs the search returned.</summary>
    public int Neighbours { get; private init; }

    public string? Error { get; private init; }

    public static RecommendationResult Success(
        IReadOnlyList<Suggestion> suggestions,
        int poolSize,
        int neighbours) => new()
        {
            Succeeded = true,
            Suggestions = suggestions,
            PoolSize = poolSize,
            Neighbours = neighbours,
        };

    public static RecommendationResult Failure(string error) =>
        new() { Succeeded = false, Error = error };
}
