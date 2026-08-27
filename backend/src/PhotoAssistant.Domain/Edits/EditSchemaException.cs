namespace PhotoAssistant.Domain.Edits;

/// <summary>
/// Thrown for anything the edit schema refuses.
/// </summary>
/// <remarks>
/// Never used to signal a repaired value: the schema rejects rather than repairs,
/// so that the renderer may assume its input is valid. A misspelled parameter
/// quietly dropped would render as neutral, and the difference would surface only
/// as an unexplained fitting residual.
/// </remarks>
public sealed class EditSchemaException : Exception
{
    public EditSchemaException(string message) : base(message)
    {
    }

    public EditSchemaException(string message, Exception inner) : base(message, inner)
    {
    }
}
