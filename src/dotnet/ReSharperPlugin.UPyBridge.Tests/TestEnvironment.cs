using System.Threading;
using JetBrains.Application.BuildScript.Application.Zones;
using JetBrains.ReSharper.Feature.Services;
using JetBrains.ReSharper.Psi.CSharp;
using JetBrains.ReSharper.TestFramework;
using JetBrains.TestFramework;
using JetBrains.TestFramework.Application.Zones;
using NUnit.Framework;

[assembly: Apartment(ApartmentState.STA)]

namespace ReSharperPlugin.UPyBridge.Tests
{
    [ZoneDefinition]
    public class UPyBridgeTestEnvironmentZone : ITestsEnvZone, IRequire<PsiFeatureTestZone>, IRequire<IUPyBridgeZone> { }

    [ZoneMarker]
    public class ZoneMarker : IRequire<ICodeEditingZone>, IRequire<ILanguageCSharpZone>, IRequire<UPyBridgeTestEnvironmentZone> { }

    [SetUpFixture]
    public class UPyBridgeTestsAssembly : ExtensionTestEnvironmentAssembly<UPyBridgeTestEnvironmentZone> { }
}
