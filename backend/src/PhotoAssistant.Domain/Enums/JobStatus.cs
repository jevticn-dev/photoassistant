namespace PhotoAssistant.Domain.Enums;

/// <summary>
/// Lifecycle of a queued job. Also used for pipeline manifest entries, which
/// move through the same states.
/// </summary>
public enum JobStatus
{
    Pending,
    Running,
    Done,
    Failed,
}
