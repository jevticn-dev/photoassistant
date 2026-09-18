using System.Reflection;
using Microsoft.AspNetCore.Mvc;

namespace PhotoAssistant.Api.Tests.Architecture;

/// <summary>
/// Controllers may depend on <c>Application</c> and on the framework, and on
/// nothing else.
///
/// <para>
/// This is the gap <see cref="LayerDependencyTests"/> cannot close. That one
/// compares assembly references, and <c>Api → Infrastructure</c> is a legal
/// reference — the API composes the container, so it has to see the concrete
/// implementations. What it must not do is <em>use</em> them: a controller that
/// injects a <c>DbContext</c>, an S3 client or an <see cref="HttpClient"/> has
/// put a use case in the transport layer, where it cannot be tested without a
/// web request and cannot be reused by anything else.
/// </para>
///
/// <para>
/// Checked by constructor parameter rather than by every type a method touches:
/// that is where dependencies enter a controller, it is unambiguous, and it
/// cannot produce a false positive over an incidental type name.
/// </para>
/// </summary>
public class ControllerDependencyTests
{
    private static readonly Assembly Api = typeof(Program).Assembly;

    /// <summary>
    /// Namespaces a controller must not take a dependency from. Infrastructure
    /// is ours; the rest are the packages it exists to wrap, named here so the
    /// rule also catches a client injected straight from a NuGet package
    /// without passing through our own assembly.
    /// </summary>
    private static readonly string[] ForbiddenNamespaces =
    [
        "PhotoAssistant.Infrastructure",
        "Microsoft.EntityFrameworkCore",
        "Npgsql",
        "Pgvector",
        "Amazon",
        "Microsoft.AspNetCore.Identity",
    ];

    public static TheoryData<Type> Controllers()
    {
        var data = new TheoryData<Type>();

        foreach (var controller in Api.GetTypes()
            .Where(type => typeof(ControllerBase).IsAssignableFrom(type) && !type.IsAbstract)
            .OrderBy(type => type.FullName, StringComparer.Ordinal))
        {
            data.Add(controller);
        }

        return data;
    }

    [Fact]
    public void There_is_at_least_one_controller_to_check()
    {
        // Without this, deleting every controller would make the suite below
        // pass by having nothing to say.
        Assert.NotEmpty(Controllers());
    }

    [Theory]
    [MemberData(nameof(Controllers))]
    public void Controller_depends_only_on_the_application_layer(Type controller)
    {
        var offenders = controller
            .GetConstructors()
            .SelectMany(constructor => constructor.GetParameters())
            .Select(parameter => parameter.ParameterType)
            .Where(IsForbidden)
            .Select(type => type.FullName!)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        Assert.True(
            offenders.Length == 0,
            $"{controller.Name} injects {string.Join(", ", offenders)}. A controller validates "
                + "input, calls a use case from Application, and maps the result; storage, HTTP "
                + "and Identity belong behind an interface that Infrastructure implements "
                + "(.claude/rules/backend.md).");
    }

    [Theory]
    [MemberData(nameof(Controllers))]
    public void Controller_does_not_reach_for_an_http_client(Type controller)
    {
        // Named separately because HttpClient lives in System.Net.Http, which is
        // too broad a namespace to forbid wholesale. The ML service is reached
        // through a typed client registered in Infrastructure, never from here.
        var injectsHttp = controller
            .GetConstructors()
            .SelectMany(constructor => constructor.GetParameters())
            .Any(parameter =>
                parameter.ParameterType == typeof(HttpClient)
                || parameter.ParameterType == typeof(IHttpClientFactory));

        Assert.False(
            injectsHttp,
            $"{controller.Name} injects an HTTP client. Calls to the ML service go through a "
                + "typed client behind an Application interface.");
    }

    [Fact]
    public void The_rule_recognises_a_storage_dependency()
    {
        // A guard that has never been seen to fire is a guard nobody knows
        // works. These two assert on the detector itself, using the exact types
        // a real slip would introduce.
        Assert.True(IsForbidden(typeof(PhotoAssistant.Infrastructure.Persistence.PhotoAssistantDbContext)));
        Assert.True(IsForbidden(typeof(Microsoft.EntityFrameworkCore.DbContext)));
    }

    [Fact]
    public void The_rule_leaves_the_application_layer_alone()
    {
        Assert.False(IsForbidden(typeof(PhotoAssistant.Application.Authentication.IAuthenticationService)));
        Assert.False(IsForbidden(typeof(CancellationToken)));
    }

    private static bool IsForbidden(Type type)
    {
        var candidates = type.IsGenericType
            ? new[] { type }.Concat(type.GetGenericArguments())
            : [type];

        return candidates.Any(candidate =>
            candidate.Namespace is { } ns
            && ForbiddenNamespaces.Any(forbidden =>
                ns.Equals(forbidden, StringComparison.Ordinal)
                || ns.StartsWith(forbidden + ".", StringComparison.Ordinal)));
    }
}
