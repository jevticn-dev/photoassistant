using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// What the system suggested and what the user did about it. Two purposes: a
/// live quality metric once the system is in use, and eventually a third source
/// of training examples (adapter 3).
/// </summary>
public class Choice
{
    public Guid Id { get; set; }

    public Guid UserId { get; set; }

    public Guid PhotoId { get; set; }
    public Photo Photo { get; set; } = null!;

    /// <summary>
    /// The three recipes that were shown, with where each came from. Raw JSON:
    /// this is a log record, so it keeps the shape it had when it was written
    /// even if the schema later changes.
    /// </summary>
    public string ShownSuggestions { get; set; } = string.Empty;

    public ChoiceOutcome Outcome { get; set; }

    /// <summary>Set only when <see cref="Outcome"/> is Refined.</summary>
    public string? FinalEdit { get; set; }

    public DateTimeOffset CreatedAt { get; set; }
}
