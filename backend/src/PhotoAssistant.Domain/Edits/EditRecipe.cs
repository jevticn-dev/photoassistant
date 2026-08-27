using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace PhotoAssistant.Domain.Edits;

/// <summary>
/// The edit schema v1 as a C# model — one edit, in the format every part of the
/// system speaks.
/// </summary>
/// <remarks>
/// <para>
/// Follows <c>docs/edit_schema_v1.md</c>. One of three models of the same format;
/// the other two are the pydantic model in <c>ml/photoassistant/schema/model.py</c>
/// and the TypeScript model in <c>frontend/src/app/renderer/schema.ts</c>.
/// Agreement between them is proven over the shared fixtures in
/// <c>fixtures/edits/</c> rather than assumed — see <c>EditRecipeTests</c>.
/// </para>
/// <para>
/// Two things this model deliberately does, matching the other two. It
/// <b>rejects rather than repairs</b>: a recipe outside the declared ranges, or
/// with a tone curve breaking <c>RENDERER_SPEC.md</c> §6.1, throws. And it
/// <b>always emits every key</b>: parsing accepts an omitted group and fills in
/// the neutral value, while serialising writes the full document, which keeps the
/// canonical form single-valued and the agreement test meaningful.
/// </para>
/// <para>
/// It lives in Domain and references nothing: <c>System.Text.Json</c> ships with
/// the runtime, so the innermost layer keeps its rule of no dependencies. Naming
/// follows the same split as the TypeScript model — PascalCase members, snake_case
/// on the wire, mapped at the boundary.
/// </para>
/// </remarks>
public sealed record EditRecipe
{
    public const int SchemaVersion = 1;

    /// <summary>Every parameter but exposure shares this symmetric interval.</summary>
    private const double NormalisedLimit = 100.0;

    /// <summary>Exposure is in stops and keeps physical meaning: +1 is twice the light.</summary>
    private const double ExposureLimit = 5.0;

    /// <summary>
    /// Smallest gap allowed between two curve control points on the x axis
    /// (<c>RENDERER_SPEC.md</c> §6.1, added by ADR-20).
    /// </summary>
    /// <remarks>
    /// One step of the 1024-entry table. Strictly increasing is not enough: two
    /// points a denormal apart still increase, and the secant slope between them
    /// overflows, which turns every pixel of the image into NaN.
    /// </remarks>
    public const double MinPointSpacing = 1.0 / 1023.0;

    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        // An unknown key is an error, not something to ignore. A misspelled
        // parameter quietly dropped would render as neutral, and the difference
        // would surface only as an unexplained fitting residual.
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        PropertyNameCaseInsensitive = false,
    };

    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
    };

    [JsonPropertyName("schema")]
    public int Schema { get; init; } = SchemaVersion;

    [JsonPropertyName("white_balance")]
    public WhiteBalance WhiteBalance { get; init; } = new();

    [JsonPropertyName("tone")]
    public Tone Tone { get; init; } = new();

    [JsonPropertyName("color")]
    public Color Color { get; init; } = new();

    [JsonPropertyName("tone_curve")]
    public ToneCurve ToneCurve { get; init; } = new();

    /// <summary>True when the recipe is the identity.</summary>
    /// <remarks>
    /// <c>JsonIgnore</c> is load-bearing, not tidiness. System.Text.Json
    /// serialises every public getter, so without it this computed property would
    /// appear as a key in the output — and the canonical form would carry a field
    /// the Python and TypeScript models know nothing about. The agreement test
    /// caught exactly that.
    /// </remarks>
    [JsonIgnore]
    public bool IsNeutral => Equals(new EditRecipe());

    /// <summary>Parse a recipe document and validate it, or throw <see cref="EditSchemaException"/>.</summary>
    /// <remarks>
    /// The schema version is required here but defaulted on the model, and the
    /// difference is deliberate. <c>new EditRecipe()</c> in code means a neutral
    /// recipe of the version this code speaks; a stored document has to say which
    /// version it is, or the promise that <c>schema: 1</c> stays readable forever
    /// has nothing to stand on.
    /// </remarks>
    public static EditRecipe FromJson(string json)
    {
        RequireSchemaVersion(json);

        EditRecipe? recipe;
        try
        {
            recipe = JsonSerializer.Deserialize<EditRecipe>(json, ReadOptions);
        }
        catch (JsonException error)
        {
            throw new EditSchemaException($"the recipe is not valid JSON: {error.Message}", error);
        }

        if (recipe is null)
        {
            throw new EditSchemaException("the recipe is null");
        }

        recipe.Validate();
        return recipe;
    }

    /// <summary>Serialise to the canonical form: every key, in schema order.</summary>
    /// <remarks>
    /// Note what canonical can and cannot mean across three languages. Key order
    /// and content are fixed here, but the text is not comparable: JavaScript
    /// cannot distinguish 0 from 0.0 when stringifying, and C# writes doubles in
    /// its own shortest round-trippable form. The agreement test therefore
    /// compares parsed values, not bytes.
    /// </remarks>
    public string ToJson() => JsonSerializer.Serialize(this, WriteOptions) + "\n";

    /// <summary>Enforce every rule the other two models enforce.</summary>
    public void Validate()
    {
        // edit_schema §7: a reader refuses a schema newer than it understands.
        // Older versions stay readable forever, which is why extensions are
        // additive only.
        if (Schema != SchemaVersion)
        {
            throw new EditSchemaException(
                $"unsupported schema version {Schema}; this reader understands {SchemaVersion}");
        }

        Require(WhiteBalance.Temperature, NormalisedLimit, "white_balance.temperature");
        Require(WhiteBalance.Tint, NormalisedLimit, "white_balance.tint");

        Require(Tone.Exposure, ExposureLimit, "tone.exposure");
        Require(Tone.Contrast, NormalisedLimit, "tone.contrast");
        Require(Tone.Highlights, NormalisedLimit, "tone.highlights");
        Require(Tone.Shadows, NormalisedLimit, "tone.shadows");
        Require(Tone.Whites, NormalisedLimit, "tone.whites");
        Require(Tone.Blacks, NormalisedLimit, "tone.blacks");

        Require(Color.Saturation, NormalisedLimit, "color.saturation");
        Require(Color.Vibrance, NormalisedLimit, "color.vibrance");

        ValidateCurve(ToneCurve.Points);
    }

    private static void RequireSchemaVersion(string json)
    {
        JsonNode? node;
        try
        {
            node = JsonNode.Parse(json);
        }
        catch (JsonException error)
        {
            throw new EditSchemaException($"the recipe is not valid JSON: {error.Message}", error);
        }

        if (node is not JsonObject document)
        {
            throw new EditSchemaException("the recipe must be an object");
        }

        if (!document.ContainsKey("schema"))
        {
            throw new EditSchemaException("the recipe must declare a schema version");
        }
    }

    private static void Require(double value, double limit, string where)
    {
        if (!double.IsFinite(value))
        {
            throw new EditSchemaException($"{where} must be a finite number, got {value}");
        }

        if (value < -limit || value > limit)
        {
            throw new EditSchemaException($"{where} must be within [{-limit}, {limit}], got {value}");
        }
    }

    private static void ValidateCurve(IReadOnlyList<CurvePoint> points)
    {
        if (points.Count < 2)
        {
            throw new EditSchemaException("a tone curve needs at least two points");
        }

        foreach (var point in points)
        {
            RequireUnit(point.X, "tone_curve.points x");
            RequireUnit(point.Y, "tone_curve.points y");
        }

        if (points[0].X != 0.0 || points[^1].X != 1.0)
        {
            // Without both endpoints the curve is undefined over part of the input
            // range, and the implementations would have to invent the same
            // extrapolation rule.
            throw new EditSchemaException(
                $"the first x must be 0 and the last 1, got {points[0].X} and {points[^1].X}");
        }

        for (var i = 1; i < points.Count; i++)
        {
            if (points[i].X <= points[i - 1].X)
            {
                throw new EditSchemaException($"x values must increase strictly, got {Xs(points)}");
            }

            if (points[i].X - points[i - 1].X < MinPointSpacing)
            {
                throw new EditSchemaException(
                    $"x values must be at least {MinPointSpacing} apart, got {Xs(points)}");
            }
        }
    }

    private static void RequireUnit(double value, string where)
    {
        if (!double.IsFinite(value) || value < 0.0 || value > 1.0)
        {
            throw new EditSchemaException($"{where} must be within [0, 1], got {value}");
        }
    }

    private static string Xs(IReadOnlyList<CurvePoint> points) =>
        string.Join(", ", points.Select(point => point.X));
}

public sealed record WhiteBalance
{
    [JsonPropertyName("temperature")]
    public double Temperature { get; init; }

    [JsonPropertyName("tint")]
    public double Tint { get; init; }
}

public sealed record Tone
{
    [JsonPropertyName("exposure")]
    public double Exposure { get; init; }

    [JsonPropertyName("contrast")]
    public double Contrast { get; init; }

    [JsonPropertyName("highlights")]
    public double Highlights { get; init; }

    [JsonPropertyName("shadows")]
    public double Shadows { get; init; }

    [JsonPropertyName("whites")]
    public double Whites { get; init; }

    [JsonPropertyName("blacks")]
    public double Blacks { get; init; }
}

public sealed record Color
{
    [JsonPropertyName("saturation")]
    public double Saturation { get; init; }

    [JsonPropertyName("vibrance")]
    public double Vibrance { get; init; }
}

/// <summary>
/// Control points of the master tone curve, not the curve itself.
/// </summary>
/// <remarks>
/// The interpolated curve and its 1024-entry LUT are built by the renderer
/// (<c>RENDERER_SPEC.md</c> §6); the schema only carries the points.
/// </remarks>
public sealed record ToneCurve
{
    private static readonly CurvePoint[] Diagonal = [new(0.0, 0.0), new(1.0, 1.0)];

    [JsonPropertyName("points")]
    public IReadOnlyList<CurvePoint> Points { get; init; } = Diagonal;

    [JsonIgnore]
    public bool IsNeutral =>
        Points.Count == 2
        && Points[0] == new CurvePoint(0.0, 0.0)
        && Points[1] == new CurvePoint(1.0, 1.0);

    /// <summary>Value equality over the points, which a record does not give for free.</summary>
    /// <remarks>
    /// A record compares its members with <c>EqualityComparer&lt;T&gt;.Default</c>,
    /// and for a collection that is <b>reference</b> equality: two lists holding
    /// the same points would compare unequal, so a recipe parsed from its own
    /// serialised form would not equal itself. Every other member here is a
    /// double, which is why this is the only place that needs saying.
    /// </remarks>
    public bool Equals(ToneCurve? other) =>
        other is not null && Points.SequenceEqual(other.Points);

    public override int GetHashCode()
    {
        var hash = default(HashCode);
        foreach (var point in Points)
        {
            hash.Add(point);
        }

        return hash.ToHashCode();
    }
}
