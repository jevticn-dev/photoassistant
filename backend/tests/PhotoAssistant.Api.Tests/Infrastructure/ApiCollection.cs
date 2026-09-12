namespace PhotoAssistant.Api.Tests.Infrastructure;

/// <summary>
/// One <see cref="ApiFactory"/> for the whole assembly, because the tests share
/// one database and migrating it is not safe to do twice at once.
/// </summary>
/// <remarks>
/// With <c>IClassFixture</c> every test class gets its own factory, and xUnit runs
/// different classes in parallel — so two instances called <c>MigrateAsync</c>
/// against the same database at the same time. When nothing is pending both are a
/// no-op and the suite is green, which is why this survived two phases. When there
/// *are* pending migrations the two race, and the loser fails with
/// <c>42701: column "excluded_reason" of relation "examples" already exists</c>.
///
/// That is every CI run, where the database is created fresh, and the first local
/// run after a new migration. The same failure was once written off as load from
/// an unrelated job, which it was not.
///
/// A collection fixture is created once and shared, so the migration runs once.
/// Classes inside a collection also do not run in parallel with each other, which
/// is the honest description of what these tests are: several suites over one
/// database.
/// </remarks>
[CollectionDefinition(Name)]
public sealed class ApiCollection : ICollectionFixture<ApiFactory>
{
    public const string Name = "api";
}
