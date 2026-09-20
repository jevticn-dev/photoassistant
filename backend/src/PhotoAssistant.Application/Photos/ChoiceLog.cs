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
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public static string Serialise(IReadOnlyList<Suggestion> shown, int? chosenIndex) =>
        JsonSerializer.Serialize(
            new
            {
                // Version of this log shape, not of the edit schema. The
                // recipes inside carry their own `schema` field; this one says
                // how the envelope around them is laid out, so a reader can
                // tell the two apart.
                log = 1,
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
}
