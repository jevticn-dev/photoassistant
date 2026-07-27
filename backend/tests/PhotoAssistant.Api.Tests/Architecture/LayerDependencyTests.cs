using System.Reflection;

namespace PhotoAssistant.Api.Tests.Architecture;

/// <summary>
/// Clean Architecture allows dependencies to point inwards only:
/// Api → Application, Infrastructure → Application → Domain.
///
/// The assertions below are deliberately all negative. The compiler drops a
/// reference an assembly never actually uses, so "X does not reference Y" is
/// sound while "X references Y" would be flaky.
/// </summary>
public class LayerDependencyTests
{
    private static readonly Assembly Domain = typeof(PhotoAssistant.Domain.AssemblyMarker).Assembly;
    private static readonly Assembly Application = typeof(PhotoAssistant.Application.AssemblyMarker).Assembly;
    private static readonly Assembly Infrastructure = typeof(PhotoAssistant.Infrastructure.AssemblyMarker).Assembly;

    private static string[] ReferencedProjectAssemblies(Assembly assembly) =>
        assembly.GetReferencedAssemblies()
            .Select(reference => reference.Name!)
            .Where(name => name.StartsWith("PhotoAssistant.", StringComparison.Ordinal))
            .ToArray();

    [Fact]
    public void Domain_depends_on_no_other_project()
    {
        Assert.Empty(ReferencedProjectAssemblies(Domain));
    }

    [Theory]
    [InlineData("PhotoAssistant.Infrastructure")]
    [InlineData("PhotoAssistant.Api")]
    public void Application_does_not_depend_on_outer_layers(string forbidden)
    {
        Assert.DoesNotContain(forbidden, ReferencedProjectAssemblies(Application));
    }

    [Fact]
    public void Infrastructure_does_not_depend_on_the_api()
    {
        Assert.DoesNotContain("PhotoAssistant.Api", ReferencedProjectAssemblies(Infrastructure));
    }
}
