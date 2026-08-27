using System.Text.Json;
using System.Text.Json.Nodes;
using PhotoAssistant.Domain.Edits;

namespace PhotoAssistant.Api.Tests.Edits;

/// <summary>
/// Agreement over the shared fixtures, and the validation rules behind it.
/// </summary>
/// <remarks>
/// <para>
/// The edit schema exists as three models — Python, TypeScript and this one.
/// Agreement is proven rather than assumed: each parses the same files from
/// <c>fixtures/edits/</c> and re-serialising must produce the same document
/// (<c>docs/edit_schema_v1.md</c> §8). This is the C# third of that claim, and
/// the assertions are deliberately the same ones as
/// <c>ml/tests/test_schema_roundtrip.py</c> and <c>schema.spec.ts</c>.
/// </para>
/// <para>
/// The fixtures are read from the repository rather than copied into the test
/// project, which is the whole point: three languages agreeing on three copies
/// would prove nothing.
/// </para>
/// <para>
/// What "the same document" means, precisely. The comparison is over parsed
/// values, not bytes. <c>JSON.stringify</c> writes <c>0</c> where Python writes
/// <c>0.0</c>, and C# writes doubles in its own shortest round-trippable form;
/// none is wrong. Comparing bytes would turn a language detail into a spurious
/// failure and tempt someone to encode numbers as strings to work around it.
/// </para>
/// </remarks>
public class EditRecipeTests
{
    private static readonly string[] ExpectedFixtures =
        ["curve_only", "extreme", "neutral", "warm_bright"];

    private static readonly DirectoryInfo Fixtures = FindFixtures();

    private static DirectoryInfo FindFixtures()
    {
        // Walk up from the test assembly rather than hard-coding a relative path:
        // the output directory depends on configuration and target framework, and
        // a path that only works in Debug is a trap for whoever changes it.
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "fixtures", "edits");
            if (Directory.Exists(candidate))
            {
                return new DirectoryInfo(candidate);
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException(
            $"no fixtures/edits above {AppContext.BaseDirectory}");
    }

    private static string Read(string name) =>
        File.ReadAllText(Path.Combine(Fixtures.FullName, $"{name}.json"));

    /// <summary>
    /// Structural equality over parsed JSON, with numbers compared as doubles.
    /// </summary>
    /// <remarks>
    /// Written out rather than using <c>JsonNode.DeepEquals</c> so that the rule
    /// this test depends on is visible: two documents agree when their shapes and
    /// their numeric values agree, whatever spelling either side chose for a
    /// number.
    /// </remarks>
    private static bool SameDocument(JsonNode? left, JsonNode? right)
    {
        switch (left, right)
        {
            case (null, null):
                return true;

            case (JsonObject a, JsonObject b):
                if (a.Count != b.Count)
                {
                    return false;
                }

                foreach (var (key, value) in a)
                {
                    if (!b.TryGetPropertyValue(key, out var other) || !SameDocument(value, other))
                    {
                        return false;
                    }
                }

                return true;

            case (JsonArray a, JsonArray b):
                return a.Count == b.Count
                    && a.Zip(b).All(pair => SameDocument(pair.First, pair.Second));

            case (JsonValue a, JsonValue b):
                if (a.GetValueKind() == JsonValueKind.Number
                    && b.GetValueKind() == JsonValueKind.Number)
                {
                    return a.GetValue<double>().Equals(b.GetValue<double>());
                }

                return a.ToJsonString() == b.ToJsonString();

            default:
                return false;
        }
    }

    private static void AssertSameDocument(string expected, string actual)
    {
        Assert.True(
            SameDocument(JsonNode.Parse(expected), JsonNode.Parse(actual)),
            $"documents differ.\nexpected:\n{expected}\nactual:\n{actual}");
    }

    private static string CurveDocument(string points) =>
        "{\"schema\": 1, \"tone_curve\": {\"points\": " + points + "}}";

    [Fact]
    public void The_expected_fixtures_are_present()
    {
        // Guards the tests below: iterating an empty directory passes vacuously.
        var found = Fixtures.GetFiles("*.json")
            .Select(file => Path.GetFileNameWithoutExtension(file.Name))
            .Order(StringComparer.Ordinal)
            .ToArray();

        Assert.Equal(ExpectedFixtures, found);
    }

    [Theory]
    [InlineData("curve_only")]
    [InlineData("extreme")]
    [InlineData("neutral")]
    [InlineData("warm_bright")]
    public void Round_trip_preserves_the_document(string name)
    {
        var text = Read(name);

        var reserialised = EditRecipe.FromJson(text).ToJson();

        AssertSameDocument(text, reserialised);
    }

    [Theory]
    [InlineData("curve_only")]
    [InlineData("extreme")]
    [InlineData("neutral")]
    [InlineData("warm_bright")]
    public void Round_trip_is_stable_at_the_model_level(string name)
    {
        var recipe = EditRecipe.FromJson(Read(name));

        Assert.Equal(recipe, EditRecipe.FromJson(recipe.ToJson()));
    }

    [Theory]
    [InlineData("curve_only")]
    [InlineData("extreme")]
    [InlineData("neutral")]
    [InlineData("warm_bright")]
    public void Every_fixture_declares_the_supported_version(string name)
    {
        Assert.Equal(EditRecipe.SchemaVersion, EditRecipe.FromJson(Read(name)).Schema);
    }

    [Fact]
    public void The_neutral_fixture_is_the_identity_recipe()
    {
        Assert.True(EditRecipe.FromJson(Read("neutral")).IsNeutral);
    }

    [Theory]
    [InlineData("curve_only")]
    [InlineData("extreme")]
    [InlineData("warm_bright")]
    public void The_other_fixtures_are_not_neutral(string name)
    {
        Assert.False(EditRecipe.FromJson(Read(name)).IsNeutral);
    }

    [Fact]
    public void Curve_only_touches_nothing_but_the_curve()
    {
        // Isolates the LUT path: any difference it renders comes from the curve
        // alone.
        var recipe = EditRecipe.FromJson(Read("curve_only"));
        var neutral = new EditRecipe();

        Assert.Equal(neutral.WhiteBalance, recipe.WhiteBalance);
        Assert.Equal(neutral.Tone, recipe.Tone);
        Assert.Equal(neutral.Color, recipe.Color);
        Assert.False(recipe.ToneCurve.IsNeutral);
    }

    [Fact]
    public void An_omitted_group_reads_as_neutral_and_is_written_back()
    {
        // Parsing is lenient about omissions, serialising is not: the canonical
        // form is always full.
        var recipe = EditRecipe.FromJson("""{"schema": 1, "color": {"vibrance": 30.0}}""");

        Assert.Equal(0.0, recipe.Tone.Exposure);
        Assert.Equal(0.0, recipe.Color.Saturation);
        Assert.Equal(30.0, recipe.Color.Vibrance);

        var written = JsonNode.Parse(recipe.ToJson())!.AsObject();
        Assert.Equal(
            ["color", "schema", "tone", "tone_curve", "white_balance"],
            written.Select(pair => pair.Key).Order(StringComparer.Ordinal));

        AssertSameDocument("[[0,0],[1,1]]", written["tone_curve"]!["points"]!.ToJsonString());
    }

    [Fact]
    public void A_newer_schema_is_refused()
    {
        // edit_schema §7: a reader refuses what it does not understand rather
        // than guessing at it.
        var error = Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson("""{"schema": 2}"""));

        Assert.Contains("unsupported schema version", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void An_unknown_key_is_refused()
    {
        // A misspelled parameter silently dropped would render as neutral and
        // hide as fitting residual.
        Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson("""{"schema": 1, "tone": {"exposure": 0.0, "clarity": 40.0}}"""));
    }

    [Theory]
    [InlineData("""{"schema": 1, "tone": {"exposure": 5.5}}""")]
    [InlineData("""{"schema": 1, "tone": {"contrast": 101.0}}""")]
    [InlineData("""{"schema": 1, "white_balance": {"temperature": -101.0}}""")]
    [InlineData("""{"schema": 1, "color": {"vibrance": 200.0}}""")]
    public void Values_outside_the_declared_range_are_refused(string document)
    {
        Assert.Throws<EditSchemaException>(() => EditRecipe.FromJson(document));
    }

    [Theory]
    [InlineData("[[0.0, 0.0]]")]
    [InlineData("[[0.2, 0.0], [1.0, 1.0]]")]
    [InlineData("[[0.0, 0.0], [0.8, 1.0]]")]
    [InlineData("[[0.0, 0.0], [0.5, 0.4], [0.5, 0.6], [1.0, 1.0]]")]
    [InlineData("[[0.0, 0.0], [0.7, 0.4], [0.3, 0.6], [1.0, 1.0]]")]
    [InlineData("[[0.0, 0.0], [0.5, 1.4], [1.0, 1.0]]")]
    public void A_curve_breaking_spec_6_1_is_refused(string points)
    {
        Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson(CurveDocument(points)));
    }

    [Theory]
    [InlineData("[[0.0, 0.0], [2.2e-309, 1.0], [1.0, 0.0]]")]
    [InlineData("[[0.0, 0.0], [0.0005, 0.5], [1.0, 1.0]]")]
    [InlineData("[[0.0, 0.0], [0.9999, 0.5], [1.0, 1.0]]")]
    public void Curve_points_closer_than_one_table_step_are_refused(string points)
    {
        // ADR-20. Strictly increasing is not enough: the first case satisfies it
        // and still overflows the secant slope, turning every pixel of the image
        // into NaN. The rule has to hold identically in all three models or they
        // stop agreeing on what a valid recipe is.
        var error = Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson(CurveDocument(points)));

        Assert.Contains("at least", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void A_lifted_black_point_is_allowed()
    {
        // Only x is constrained to the endpoints; y is free, which is what a
        // faded look needs.
        var recipe = EditRecipe.FromJson(
            """{"schema": 1, "tone_curve": {"points": [[0.0, 0.1], [1.0, 0.9]]}}""");

        Assert.Equal([new CurvePoint(0.0, 0.1), new CurvePoint(1.0, 0.9)], recipe.ToneCurve.Points);
    }

    [Fact]
    public void A_value_that_is_not_a_number_is_refused()
    {
        Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson("""{"schema": 1, "tone": {"exposure": "1.0"}}"""));
    }

    [Fact]
    public void A_recipe_with_no_schema_version_is_refused()
    {
        // The other two models refuse this too: the version is what makes a stored
        // recipe readable forever, so a document without one is not a recipe.
        Assert.Throws<EditSchemaException>(
            () => EditRecipe.FromJson("""{"tone": {"exposure": 1.0}}"""));
    }
}
