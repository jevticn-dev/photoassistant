using PhotoAssistant.Domain.Entities;

namespace PhotoAssistant.Application.Photos;

/// <summary>
/// What was shown and what was done about it.
///
/// <para>
/// The suggestions are sent back by the client rather than recomputed here.
/// They have to be: the search is not deterministic across time — the corpus
/// can change — and what belongs in the log is what the person actually saw,
/// not what a second query would produce.
/// </para>
/// </summary>
public sealed record RecordChoiceRequest
{
    public required Guid PhotoId { get; init; }

    public required Guid UserId { get; init; }

    /// <summary>All three, in the order they were shown.</summary>
    public required IReadOnlyList<Suggestion> Shown { get; init; }

    /// <summary>
    /// Index of the chosen one, or null when the person went to the editor
    /// without taking any of them.
    /// </summary>
    public required int? ChosenIndex { get; init; }
}

public sealed record RecordChoiceResult
{
    private RecordChoiceResult()
    {
    }

    public bool Succeeded { get; private init; }

    public Guid ChoiceId { get; private init; }

    public bool NotFound { get; private init; }

    public string? Error { get; private init; }

    public static RecordChoiceResult Success(Guid id) =>
        new() { Succeeded = true, ChoiceId = id };

    public static RecordChoiceResult Missing() => new() { NotFound = true };

    public static RecordChoiceResult Failure(string error) => new() { Error = error };
}

/// <summary>
/// Writes one row to <c>choices</c>.
///
/// <para>
/// Plan §1.1 calls this a live quality metric and, later, a third source of
/// training examples. Both need the same thing: the three that were offered
/// next to what the person did. A log of only the accepted edit would say
/// nothing about whether the other two were worse or simply unseen.
/// </para>
/// </summary>
public sealed class RecordChoiceHandler(
    IPhotoRepository photos,
    IChoiceRepository choices,
    TimeProvider clock)
{
    public async Task<RecordChoiceResult> RecordAsync(
        RecordChoiceRequest request,
        CancellationToken cancellationToken)
    {
        if (request.Shown.Count == 0)
        {
            return RecordChoiceResult.Failure("No suggestions were given to record.");
        }

        if (request.ChosenIndex is { } index && (index < 0 || index >= request.Shown.Count))
        {
            return RecordChoiceResult.Failure("The chosen suggestion is not one of those shown.");
        }

        var photo = await photos.FindForUserAsync(request.PhotoId, request.UserId, cancellationToken);
        if (photo is null)
        {
            return RecordChoiceResult.Missing();
        }

        var choice = new Choice
        {
            Id = Guid.CreateVersion7(),
            UserId = request.UserId,
            PhotoId = request.PhotoId,
            ShownSuggestions = ChoiceLog.Serialise(request.Shown, request.ChosenIndex),

            // Accepted now, Refined later: taking a suggestion and then moving a
            // slider is a different outcome, and the editor is what knows that
            // happened. Rejected is for going in with none of them.
            Outcome = request.ChosenIndex is null
                ? Domain.Enums.ChoiceOutcome.Rejected
                : Domain.Enums.ChoiceOutcome.Accepted,
            CreatedAt = clock.GetUtcNow(),
        };

        await choices.AddAsync(choice, cancellationToken);

        return RecordChoiceResult.Success(choice.Id);
    }
}
