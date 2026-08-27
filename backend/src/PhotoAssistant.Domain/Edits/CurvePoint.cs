using System.Text.Json;
using System.Text.Json.Serialization;

namespace PhotoAssistant.Domain.Edits;

/// <summary>
/// One control point of the master tone curve: (input, output), both in [0, 1].
/// </summary>
/// <remarks>
/// Serialised as the two-element array <c>[x, y]</c> the wire format uses, not as
/// an object with named members. The converter below exists for that reason
/// alone: the format is fixed by <c>docs/edit_schema_v1.md</c> and shared with two
/// other languages, so the C# shape bends to it rather than the other way round.
/// </remarks>
[JsonConverter(typeof(CurvePointConverter))]
public readonly record struct CurvePoint(double X, double Y);

internal sealed class CurvePointConverter : JsonConverter<CurvePoint>
{
    public override CurvePoint Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.StartArray)
        {
            throw new EditSchemaException("a curve point must be a pair [x, y]");
        }

        var values = new List<double>(2);
        while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
        {
            if (reader.TokenType != JsonTokenType.Number)
            {
                throw new EditSchemaException("a curve point must contain only numbers");
            }

            values.Add(reader.GetDouble());
        }

        if (values.Count != 2)
        {
            throw new EditSchemaException($"a curve point must be a pair [x, y], got {values.Count} values");
        }

        return new CurvePoint(values[0], values[1]);
    }

    public override void Write(Utf8JsonWriter writer, CurvePoint point, JsonSerializerOptions options)
    {
        writer.WriteStartArray();
        writer.WriteNumberValue(point.X);
        writer.WriteNumberValue(point.Y);
        writer.WriteEndArray();
    }
}
