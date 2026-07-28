namespace PhotoAssistant.Domain.Enums;

/// <summary>What the user did with the three suggestions they were shown.</summary>
public enum ChoiceOutcome
{
    /// <summary>Applied one of the suggestions unchanged.</summary>
    Accepted,

    /// <summary>Applied none of them.</summary>
    Rejected,

    /// <summary>Applied one and then adjusted it; the result is in <c>final_edit</c>.</summary>
    Refined,
}
