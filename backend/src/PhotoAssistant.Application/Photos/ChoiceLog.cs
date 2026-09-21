using System.Text.Json;

namespace PhotoAssistant.Application.Photos;

/// <summary>
/// How a set of suggestions is written into <c>choices.shown_suggestions</c>.
///
/// <para>
/// A log record, so it is stored as its own document rather than as rows: it
/// keeps the shape it had the day it was written even after the edit schema
/// moves on, which is exactly what makes it readable years later. The entity
/// says as much (<c>Choice.ShownSuggestions</c>).
/// </para>
/// </summary>
public static class ChoiceLog
{
    /// <summary>
    /// Version of this log shape, not of the edit schema. The recipes inside
    /// carry their own <c>schema</c> field; this one says how the envelope
    /// around them is laid out, so a reader can tell the two apart.
    /// </summary>
    private const int Version = 1;

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public static string Serialise(IReadOnlyList<Suggestion> shown, int? chosenIndex) =>
        JsonSerializer.Serialize(
            new
            {
                log = Version,
                chosen_index = chosenIndex,
                suggestions = shown.Select(suggestion => new
                {
                    suggestion.Recipe,
                    suggestion.SourceReference,
                    suggestion.Expert,
                    suggestion.SceneDistance,
                }),
            },
            Options);

    /// <summary>
    /// The recipe that was taken, or null when none was — either because the
    /// person skipped the screen or because the log predates this reader.
    ///
    /// <para>
    /// Reading a log to decide behaviour deserves a word, since a log is
    /// normally written and never looked at again. What the editor opens on
    /// <em>is</em> what was chosen, and this document is where that was
    /// recorded; copying the same recipe into a second column so the
    /// application need not read its own log would be two places to keep in
    /// step. The version is checked rather than assumed, so a log written in a
    /// later shape is passed over instead of misread.
    /// </para>
    /// </summary>
    public static JsonElement? ReadChosenRecipe(string document)
    {
        try
        {
            using var parsed = JsonDocument.Parse(document);
            var root = parsed.RootElement;

            if (!root.TryGetProperty("log", out var version) || version.GetInt32() != Version)
            {
                return null;
            }

            if (!root.TryGetProperty("chosen_index", out var index)
                || index.ValueKind != JsonValueKind.Number)
            {
                return null;
            }

            var suggestions = root.GetProperty("suggestions");
            var chosen = index.GetInt32();

            if (chosen < 0 || chosen >= suggestions.GetArrayLength())
            {
                return null;
            }

            // Cloned, because an element borrowed from a document stops being
            // readable the moment that document is disposed.
            return suggestions[chosen].GetProperty("recipe").Clone();
        }
        catch (Exception error) when (error is JsonException or KeyNotFoundException
                                          or InvalidOperationException)
        {
            // A log that cannot be read is not a reason to refuse the editor.
            // It opens on the photograph unchanged, which is a worse start but
            // a start.
            return null;
        }
    }
}
