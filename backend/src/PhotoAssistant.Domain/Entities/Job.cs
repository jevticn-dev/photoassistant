using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Domain.Entities;

/// <summary>
/// Queued background work. The queue is a table rather than a message broker
/// (ADR-7): at this scale Redis would add a moving part without measurable
/// benefit. The API inserts, the ML worker polls, the frontend asks for status.
/// </summary>
public class Job
{
    public Guid Id { get; set; }

    public JobType Type { get; set; }

    public JobStatus Status { get; set; }

    /// <summary>Input for the worker, e.g. project id and target format. Raw JSON.</summary>
    public string Payload { get; set; } = string.Empty;

    /// <summary>Output, e.g. the object key of the rendered export. Null until done.</summary>
    public string? Result { get; set; }

    public string? Error { get; set; }

    public DateTimeOffset CreatedAt { get; set; }

    public DateTimeOffset UpdatedAt { get; set; }
}
