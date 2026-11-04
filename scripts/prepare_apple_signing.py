"""Ask Xcode automatic signing for this app's development provisioning profile.

Requires an Apple developer account already configured in Xcode. Does not read or
export private keys. Generated account/device profiles stay outside the repository.
"""
import argparse
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--team',required=True)
    parser.add_argument('--device',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    project=root/'Signing.xcodeproj';project.mkdir(exist_ok=True)
    (root/'main.m').write_text('int main(int argc, char **argv) { return 0; }\n')
    # This tiny target is used only to obtain the app-specific profile from Xcode.
    # The real native/Python application is built by build_apple_clients.py.
    objects='''{
 archiveVersion=1; classes={}; objectVersion=56;
 objects={
 A00000000000000000000001={isa=PBXProject;attributes={LastUpgradeCheck=1600;TargetAttributes={A00000000000000000000002={ProvisioningStyle=Automatic;};};};buildConfigurationList=A00000000000000000000010;compatibilityVersion="Xcode 14.0";developmentRegion=en;knownRegions=(en,Base);mainGroup=A00000000000000000000003;productRefGroup=A00000000000000000000004;projectDirPath="";projectRoot="";targets=(A00000000000000000000002);};
 A00000000000000000000002={isa=PBXNativeTarget;buildConfigurationList=A00000000000000000000011;buildPhases=(A00000000000000000000005);buildRules=();dependencies=();name=SooveeCommander;productName=SooveeCommander;productReference=A00000000000000000000007;productType="com.apple.product-type.application";};
 A00000000000000000000003={isa=PBXGroup;children=(A00000000000000000000006,A00000000000000000000004);sourceTree="<group>";};
 A00000000000000000000004={isa=PBXGroup;children=(A00000000000000000000007);name=Products;sourceTree="<group>";};
 A00000000000000000000005={isa=PBXSourcesBuildPhase;buildActionMask=2147483647;files=(A00000000000000000000008);runOnlyForDeploymentPostprocessing=0;};
 A00000000000000000000006={isa=PBXFileReference;lastKnownFileType=sourcecode.c.objc;path=main.m;sourceTree="<group>";};
 A00000000000000000000007={isa=PBXFileReference;explicitFileType=wrapper.application;includeInIndex=0;path=SooveeCommander.app;sourceTree=BUILT_PRODUCTS_DIR;};
 A00000000000000000000008={isa=PBXBuildFile;fileRef=A00000000000000000000006;};
 A00000000000000000000010={isa=XCConfigurationList;buildConfigurations=(A00000000000000000000012);defaultConfigurationIsVisible=0;defaultConfigurationName=Debug;};
 A00000000000000000000011={isa=XCConfigurationList;buildConfigurations=(A00000000000000000000013);defaultConfigurationIsVisible=0;defaultConfigurationName=Debug;};
 A00000000000000000000012={isa=XCBuildConfiguration;buildSettings={SDKROOT=iphoneos;IPHONEOS_DEPLOYMENT_TARGET=17.0;};name=Debug;};
 A00000000000000000000013={isa=XCBuildConfiguration;buildSettings={CODE_SIGN_STYLE=Automatic;DEVELOPMENT_TEAM=TEAM_PLACEHOLDER;GENERATE_INFOPLIST_FILE=YES;INFOPLIST_KEY_UILaunchScreen_Generation=YES;PRODUCT_BUNDLE_IDENTIFIER=cz.soovee.commander.ios;PRODUCT_NAME="$(TARGET_NAME)";TARGETED_DEVICE_FAMILY="1,2";MARKETING_VERSION=0.18.0;CURRENT_PROJECT_VERSION=180;};name=Debug;};
 };rootObject=A00000000000000000000001;
}'''
    if not args.team.isalnum(): raise SystemExit('Invalid signing team.')
    (project/'project.pbxproj').write_text(objects.replace('TEAM_PLACEHOLDER',args.team))
    subprocess.run(['xcodebuild','-project',str(project),'-scheme','SooveeCommander','-configuration','Debug',
        '-sdk','iphoneos','-destination','id='+args.device,'-derivedDataPath',str(root/'DerivedData'),
        '-allowProvisioningUpdates','build'],check=True)
    print(root/'DerivedData/Build/Products/Debug-iphoneos/SooveeCommander.app/embedded.mobileprovision')


if __name__=='__main__':main()
