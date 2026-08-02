namespace PhotoAssistant.Domain.Enums;

/// <summary>Kind of work queued in the jobs table (ADR-7).</summary>
public enum JobType
{
    /// <summary>Render a recipe over the full-resolution original and store the result.</summary>
    Export,
}
