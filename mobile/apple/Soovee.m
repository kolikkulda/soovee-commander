// Native UIKit shell. The bundled, shared Python core owns network authorization.
#import <UIKit/UIKit.h>
#import <CoreImage/CoreImage.h>
#import <TargetConditionals.h>
#import <Python/Python.h>
#import <arpa/inet.h>
#if !TARGET_OS_TV
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <AVFoundation/AVFoundation.h>
#if !TARGET_OS_TV
#import <QuickLookThumbnailing/QuickLookThumbnailing.h>
#import <QuickLook/QuickLook.h>
#endif
#endif

static dispatch_queue_t coreQueue;
static PyObject *bridge;
static NSDictionary *translations;
static NSString *T(NSString *source) { return translations[source] ?: source; }
static UIColor *Background(void) { return [UIColor colorWithDynamicProvider:^UIColor *(UITraitCollection *traits){return traits.userInterfaceStyle==UIUserInterfaceStyleDark?[UIColor colorWithRed:.043 green:.063 blue:.125 alpha:1]:[UIColor colorWithRed:.953 green:.965 blue:.984 alpha:1];}]; }
static UIColor *Surface(void) { return [UIColor colorWithDynamicProvider:^UIColor *(UITraitCollection *traits){return traits.userInterfaceStyle==UIUserInterfaceStyleDark?[UIColor colorWithRed:.078 green:.110 blue:.188 alpha:1]:UIColor.whiteColor;}]; }
static UIColor *Accent(void) { return [UIColor colorWithRed:.1 green:.86 blue:.9 alpha:1]; }

#if !TARGET_OS_TV
@interface SooveeQRScanner : UIViewController <AVCaptureMetadataOutputObjectsDelegate>
@property(nonatomic,strong) AVCaptureSession *capture;
@property(nonatomic,strong) AVCaptureVideoPreviewLayer *preview;
@property(nonatomic,strong) dispatch_queue_t cameraQueue;
@property(nonatomic,copy) void (^result)(NSString *);
@property(nonatomic) BOOL finished;
@property(nonatomic,strong) UILabel *hint;
@end
@implementation SooveeQRScanner
- (void)viewDidLoad {
    [super viewDidLoad];self.view.backgroundColor=Background();self.cameraQueue=dispatch_queue_create("Soovee QR camera",DISPATCH_QUEUE_SERIAL);
    UIButton *cancel=[UIButton buttonWithType:UIButtonTypeSystem];[cancel setTitle:T(@"Cancel") forState:UIControlStateNormal];cancel.tintColor=UIColor.whiteColor;cancel.frame=CGRectMake(20,60,90,44);[self.view addSubview:cancel];
    [cancel addAction:[UIAction actionWithHandler:^(UIAction *action){[self dismissViewControllerAnimated:YES completion:nil];}] forControlEvents:UIControlEventTouchUpInside];
    UILabel *hint=[[UILabel alloc]initWithFrame:CGRectMake(30,125,self.view.bounds.size.width-60,80)];hint.text=T(@"Point the camera at a Soovee pairing QR.");hint.textColor=UIColor.whiteColor;hint.numberOfLines=0;hint.textAlignment=NSTextAlignmentCenter;[self.view addSubview:hint];self.hint=hint;
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL allowed){dispatch_async(dispatch_get_main_queue(),^{
        if(!self.view.window)return;
        if(!allowed){hint.text=T(@"Camera access is disabled. You can pair with a code instead.");return;}
        NSError *error=nil;AVCaptureDevice *camera=[AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];AVCaptureDeviceInput *input=camera?[AVCaptureDeviceInput deviceInputWithDevice:camera error:&error]:nil;
        self.capture=[AVCaptureSession new];AVCaptureMetadataOutput *output=[AVCaptureMetadataOutput new];
        if(!input||![self.capture canAddInput:input]||![self.capture canAddOutput:output]){hint.text=T(@"Camera is unavailable. Pair with a code instead.");return;}
        [self.capture addInput:input];[self.capture addOutput:output];[output setMetadataObjectsDelegate:self queue:dispatch_get_main_queue()];output.metadataObjectTypes=@[AVMetadataObjectTypeQRCode];
        self.preview=[AVCaptureVideoPreviewLayer layerWithSession:self.capture];self.preview.videoGravity=AVLayerVideoGravityResizeAspectFill;[self.view.layer insertSublayer:self.preview atIndex:0];[self.view setNeedsLayout];
        dispatch_async(self.cameraQueue,^{[self.capture startRunning];});
    });}];
}
- (void)viewDidLayoutSubviews {[super viewDidLayoutSubviews];self.preview.frame=self.view.bounds;}
- (void)viewDidDisappear:(BOOL)animated {[super viewDidDisappear:animated];dispatch_async(self.cameraQueue,^{[self.capture stopRunning];});}
- (void)metadataOutput:(AVCaptureMetadataOutput *)output didOutputMetadataObjects:(NSArray<__kindof AVMetadataObject *> *)objects fromConnection:(AVCaptureConnection *)connection {
    for(AVMetadataMachineReadableCodeObject *object in objects){NSString *value=object.stringValue;if(self.finished||!value.length)continue;NSURLComponents *url=[NSURLComponents componentsWithString:value];if([url.scheme isEqual:@"soovee-transfer"]&&[url.host isEqual:@"pair"]){self.finished=YES;dispatch_async(self.cameraQueue,^{[self.capture stopRunning];});[self dismissViewControllerAnimated:YES completion:^{if(self.result)self.result(value);}];return;}self.hint.text=T(@"This QR is not a Soovee pairing code. Scan the QR in Devices on your computer or TV.");}
}
@end
#endif

@interface SooveeButton : UIButton
@end
@implementation SooveeButton
- (void)didUpdateFocusInContext:(UIFocusUpdateContext *)context withAnimationCoordinator:(UIFocusAnimationCoordinator *)coordinator {
    [super didUpdateFocusInContext:context withAnimationCoordinator:coordinator];
    BOOL focused=context.nextFocusedView==self;
    self.backgroundColor=focused?Accent():[UIColor colorWithRed:.08 green:.14 blue:.23 alpha:1];
    [self setTitleColor:focused?Background():UIColor.whiteColor forState:UIControlStateNormal];
}
@end

static NSString *PythonError(void) {
    PyObject *error = PyErr_GetRaisedException();
    PyObject *text = error ? PyObject_Str(error) : NULL;
    NSString *result = text ? [NSString stringWithUTF8String:PyUnicode_AsUTF8(text)] : @"Python operation failed";
    Py_XDECREF(text); Py_XDECREF(error);
    return result;
}

static NSString *CoreCall(NSString *name, NSArray *arguments, BOOL direct) {
    if (!bridge) return @"{\"error\":\"Transfer runtime is not ready\"}";
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *function = PyObject_GetAttrString(bridge, direct ? name.UTF8String : "call");
    PyObject *args = PyTuple_New(arguments.count + (direct ? 0 : 1));
    NSUInteger offset = direct ? 0 : 1;
    if (!direct) PyTuple_SET_ITEM(args, 0, PyUnicode_FromString(name.UTF8String));
    for (NSUInteger i=0; i<arguments.count; i++) {
        id value = arguments[i];
        PyObject *object = [value isKindOfClass:NSNumber.class] ? PyLong_FromLongLong([value longLongValue]) : PyUnicode_FromString([value UTF8String]);
        PyTuple_SET_ITEM(args, i+offset, object);
    }
    PyObject *value = function ? PyObject_CallObject(function, args) : NULL;
    NSString *result;
    if (value) {
        PyObject *text = PyObject_Str(value);
        result = text ? [NSString stringWithUTF8String:PyUnicode_AsUTF8(text)] : @"";
        Py_XDECREF(text); Py_DECREF(value);
    } else {
        NSDictionary *error = @{@"error":PythonError()};
        result = [[NSString alloc] initWithData:[NSJSONSerialization dataWithJSONObject:error options:0 error:nil] encoding:NSUTF8StringEncoding];
    }
    Py_XDECREF(function); Py_DECREF(args); PyGILState_Release(gil);
    return result;
}

static NSString *StartPython(void) {
    NSString *bundle = NSBundle.mainBundle.resourcePath;
    PyPreConfig preconfig; PyPreConfig_InitIsolatedConfig(&preconfig); preconfig.utf8_mode=1;
    PyStatus status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) return status.err_msg?[NSString stringWithUTF8String:status.err_msg]:@"Python initialization failed";
    PyConfig config; PyConfig_InitIsolatedConfig(&config);
    config.buffered_stdio=0; config.write_bytecode=0; config.install_signal_handlers=0;
    PyConfig_SetBytesString(&config, &config.home, [[bundle stringByAppendingPathComponent:@"python"] UTF8String]);
    config.module_search_paths_set=1;
    for (NSString *path in @[@"python/lib/python3.14", @"python/lib/python3.14/lib-dynload", @"app"]) {
        wchar_t *wide = Py_DecodeLocale([[bundle stringByAppendingPathComponent:path] UTF8String], NULL);
        PyWideStringList_Append(&config.module_search_paths, wide); PyMem_RawFree(wide);
    }
    status = Py_InitializeFromConfig(&config); PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) return status.err_msg?[NSString stringWithUTF8String:status.err_msg]:@"Python initialization failed";
    bridge = PyImport_ImportModule("soovee_apple");
    if (!bridge) return PythonError();
    PyEval_SaveThread();
    return nil;
}

#include "FileCells.inc"
#if TARGET_OS_TV
@interface SooveeViewController : UIViewController <NSNetServiceBrowserDelegate,NSNetServiceDelegate>
#else
@interface SooveeViewController : UIViewController <UIDocumentPickerDelegate, UIDocumentInteractionControllerDelegate, NSNetServiceBrowserDelegate, NSNetServiceDelegate, UICollectionViewDelegate, UICollectionViewDragDelegate, UICollectionViewDropDelegate, QLPreviewControllerDataSource>
@property(nonatomic,copy) NSString *otherPeer;      // right (target) panel on wide screens
@property(nonatomic,copy) NSString *otherPath;
@property(nonatomic,strong) NSArray *otherEntries;
@property(nonatomic,strong) UIStackView *otherContainer;
@property(nonatomic,strong) UIStackView *otherHeader;
@property(nonatomic,strong) UICollectionView *otherCollection;
@property(nonatomic,strong) UICollectionViewDiffableDataSource<NSString *,NSString *> *otherSource;
@property(nonatomic,strong) NSArray<NSURL *> *previewURLs;
@property(nonatomic,strong) UIViewController *progressSheet;   // open while a copy, move or archive runs
@property(nonatomic,strong) UIProgressView *progressBar;
@property(nonatomic,strong) UILabel *progressName;
@property(nonatomic,strong) UILabel *progressBytes;
@property(nonatomic,strong) UILabel *progressPercent;
@property(nonatomic,strong) UILabel *progressSpeed;
@property(nonatomic,strong) NSDate *progressStarted;
@property(nonatomic,copy) NSString *progressRoute;
@property(nonatomic) BOOL progressStopped;
- (void)updateProgress:(NSDictionary *)state;
@property(nonatomic,strong) UIDocumentInteractionController *document;
@property(nonatomic,strong) UIStackView *filesContainer;
@property(nonatomic,strong) UIStackView *filesHeader;
@property(nonatomic,strong) UICollectionView *filesCollection;
@property(nonatomic,strong) UICollectionViewDiffableDataSource<NSString *,NSString *> *filesSource;
@property(nonatomic,strong) NSDictionary<NSString *,NSDictionary *> *entryByName;
@property(nonatomic,strong) NSCache *thumbnails;
@property(nonatomic,copy) NSString *filesBase;      // absolute folder of a local listing, for thumbnails, preview and sharing
@property(nonatomic,strong) UILabel *filesCount;
@property(nonatomic,strong) UIStackView *selectionBar;
@property(nonatomic) BOOL selectionMode;
@property(nonatomic,copy) NSString *searchQuery;    // non-nil while showing results of a subfolder search
@property(nonatomic) BOOL searchComplete;
#endif
@property(nonatomic,strong) UIScrollView *scroll;
@property(nonatomic,strong) UIStackView *brand;
@property(nonatomic,strong) UIStackView *content;
@property(nonatomic,strong) UILabel *status;
@property(nonatomic,strong) UILabel *code;
@property(nonatomic,strong) UILabel *endpoint;
@property(nonatomic,strong) UIImageView *qr;
@property(nonatomic,strong) NSDictionary *state;
@property(nonatomic,copy) NSString *screen;
@property(nonatomic,copy) NSString *peer;
@property(nonatomic,copy) NSString *path;
@property(nonatomic,strong) NSTimer *timer;
@property(nonatomic,strong) NSNetServiceBrowser *browser;
@property(nonatomic,strong) NSNetService *advertisement;
@property(nonatomic,strong) NSMutableArray<NSNetService *> *services;
@property(nonatomic,strong) NSMutableDictionary *nearby;
@property(nonatomic,strong) NSMutableSet<NSString *> *selection;
@property(nonatomic,strong) NSArray *fileEntries;
@property(nonatomic,copy) NSString *filter;
@property(nonatomic) NSInteger sortOrder;
@property(nonatomic) BOOL tiles;
@property(nonatomic,copy) NSString *statusPeer;
@property(nonatomic) NSInteger shownCount;   // rows built so far; large folders are shown in pages
@property(nonatomic,strong) UIAlertController *operationAlert;
@property(nonatomic,strong) UIStackView *tabs;
@property(nonatomic) BOOL pairing;
@property(nonatomic,strong) UILabel *pairingStatus;
@property(nonatomic,strong) NSMutableDictionary<NSString *,NSURL *> *folderAccess;
@property(nonatomic) BOOL choosingFolder;
- (void)beginPairing:(NSString *)invitation host:(NSString *)host port:(NSNumber *)port code:(NSString *)code;
- (void)openDevice:(NSString *)identity;
- (void)openDevice:(NSString *)identity retry:(BOOL)retry;
- (void)toast:(NSString *)text;
- (void)askCode:(NSDictionary *)device asked:(BOOL)asked;
- (void)requestCode:(NSDictionary *)device retry:(BOOL)retry;
- (void)showPairingRequest:(NSString *)name;
- (void)removePairing:(NSString *)identity name:(NSString *)name;
- (void)removePairing:(NSString *)identity name:(NSString *)name pairAgain:(BOOL)again;
- (void)call:(NSString *)name args:(NSArray *)args then:(void (^)(NSString *))complete;
- (void)addFolder;
- (void)restoreFolders;
- (void)configureFolders:(dispatch_block_t)complete;
- (void)presentApproval:(UIAlertController *)alert deadline:(NSDate *)deadline expired:(dispatch_block_t)expired;

- (void)showHome;
- (void)showTransfers;
- (void)renderFiles;
- (void)itemMenu:(NSDictionary *)item;
- (void)pickFolder:(NSString *)peer path:(NSString *)path chosen:(void (^)(NSString *))chosen;

- (void)showPairing;
- (void)showDevices;
- (void)showFiles;
- (void)showSettings;
- (void)showNearby;
- (void)showError:(NSString *)message;
- (void)updateState:(NSString *)json;
@end

static __weak SooveeViewController *controller;

__attribute__((visibility("default"), used)) int soovee_approve(const char *kind, const char *json) {
    NSString *type=[NSString stringWithUTF8String:kind];
    NSData *data=[[NSString stringWithUTF8String:json] dataUsingEncoding:NSUTF8StringEncoding];
    NSDictionary *peer=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    __block BOOL accepted=NO;
    dispatch_async(dispatch_get_main_queue(), ^{
        SooveeViewController *view=controller;
        if (!view || !view.view.window) { dispatch_semaphore_signal(done); return; }
        NSString *message;
        if ([type isEqual:@"pair"]) message=[NSString stringWithFormat:@"%@\n%@\n%@\n%@ %@\n\n%@",T(@"Confirm pairing with this device:"),peer[@"name"],peer[@"host"],T(@"Verification:"),peer[@"verification"],T(@"Allow this device to browse and upload to this app’s Shared folder? Other folders are not shared.")];
        else message=[NSString stringWithFormat:@"%@\n%@ · %@ · %@ B",T(@"Receive files from this device?"),peer[@"name"],peer[@"files"],peer[@"bytes"]];
        UIAlertController *alert=[UIAlertController alertControllerWithTitle:T(@"Confirm device access") message:message preferredStyle:UIAlertControllerStyleAlert];
        [alert addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:^(UIAlertAction *action){dispatch_semaphore_signal(done);}]];
        [alert addAction:[UIAlertAction actionWithTitle:T(@"Allow") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){accepted=YES;dispatch_semaphore_signal(done);}]];
        [view presentApproval:alert deadline:[NSDate dateWithTimeIntervalSinceNow:115] expired:^{dispatch_semaphore_signal(done);}];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC),dispatch_get_main_queue(),^{if(alert.presentingViewController)[alert dismissViewControllerAnimated:YES completion:nil];});
    });
    if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC)))return 0;
    return accepted;
}

__attribute__((visibility("default"), used)) void soovee_event(const char *json) {
    NSData *data=[[NSString stringWithUTF8String:json] dataUsingEncoding:NSUTF8StringEncoding];
    NSDictionary *event=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if([event[@"kind"] isEqual:@"pair-request"]){dispatch_async(dispatch_get_main_queue(),^{[controller showPairingRequest:event[@"name"]];});return;}
    if([event[@"kind"] isEqual:@"paired"]){dispatch_async(dispatch_get_main_queue(),^{[controller call:@"snapshot" args:@[] then:^(NSString *json){[controller updateState:json];if([controller.screen isEqual:@"pair"])[controller showDevices];}];});}
    dispatch_async(dispatch_get_main_queue(),^{NSString *message=[NSString stringWithFormat:@"%@\n%@ · %@ / %@",event[@"current"]?:event[@"message"]?:event[@"path"]?:@"",[NSByteCountFormatter stringFromByteCount:[event[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile],event[@"completed"]?:@0,event[@"files"]?:@0];if(![event[@"kind"] isEqual:@"operation"])controller.status.text=event[@"message"]?:event[@"kind"]?:@"";if(controller.operationAlert)controller.operationAlert.message=message;
#if !TARGET_OS_TV
        [controller updateProgress:event];
#endif
    });
}

@implementation SooveeViewController
- (UILabel *)label:(NSString *)text size:(CGFloat)size {
    UILabel *label=[UILabel new];label.text=text;label.textColor=TARGET_OS_TV?UIColor.whiteColor:UIColor.labelColor;label.font=[UIFont systemFontOfSize:size];label.numberOfLines=0;return label;
}
- (UIButton *)button:(NSString *)title action:(dispatch_block_t)action {
    UIButton *button=[SooveeButton buttonWithType:UIButtonTypeCustom];
    UIButtonConfiguration *configuration=[UIButtonConfiguration plainButtonConfiguration];
    configuration.title=title;configuration.baseForegroundColor=TARGET_OS_TV?UIColor.whiteColor:UIColor.labelColor;
    configuration.background.backgroundColor=TARGET_OS_TV?[UIColor colorWithRed:.08 green:.14 blue:.23 alpha:1]:Surface();
    configuration.background.cornerRadius=16;configuration.contentInsets=NSDirectionalEdgeInsetsMake(16,16,16,16);
    button.configuration=configuration;button.titleLabel.numberOfLines=0;
    button.titleLabel.font=[UIFont systemFontOfSize:TARGET_OS_TV?25:16 weight:UIFontWeightSemibold];button.contentHorizontalAlignment=UIControlContentHorizontalAlignmentLeading;
    [button addAction:[UIAction actionWithHandler:^(UIAction *value){action();}] forControlEvents:UIControlEventPrimaryActionTriggered];
    return button;
}
- (void)add:(NSString *)title action:(dispatch_block_t)action { [self.content addArrangedSubview:[self button:title action:action]]; }
- (void)viewDidLoad {
    [super viewDidLoad];controller=self;self.view.backgroundColor=Background();self.peer=@"";self.path=@"/";self.screen=@"pair";self.state=@{};self.services=[NSMutableArray new];self.nearby=[NSMutableDictionary new];self.selection=[NSMutableSet new];self.folderAccess=[NSMutableDictionary new];self.filter=@"";self.fileEntries=@[];self.tiles=[NSUserDefaults.standardUserDefaults boolForKey:@"fileGrid"];if(!TARGET_OS_TV)self.overrideUserInterfaceStyle=[NSUserDefaults.standardUserDefaults objectForKey:@"appearance"]?[NSUserDefaults.standardUserDefaults integerForKey:@"appearance"]:UIUserInterfaceStyleDark;
    NSString *language=NSLocale.preferredLanguages.firstObject;
    if([language hasPrefix:@"cs"]){NSData *data=[NSData dataWithContentsOfFile:[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"cs.json"]];if(data)translations=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];}
    UIStackView *root=[UIStackView new];root.axis=UILayoutConstraintAxisVertical;root.spacing=12;root.translatesAutoresizingMaskIntoConstraints=NO;[self.view addSubview:root];
    UILayoutGuide *safe=self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[[root.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:20],[root.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-20],[root.topAnchor constraintEqualToAnchor:safe.topAnchor constant:16],[root.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-16]]];
    UIStackView *brand=[UIStackView new];brand.axis=UILayoutConstraintAxisHorizontal;brand.alignment=UIStackViewAlignmentCenter;brand.spacing=10;UIImageView *logo=[[UIImageView alloc]initWithImage:[UIImage imageNamed:@"Icon180.png"]];logo.contentMode=UIViewContentModeScaleAspectFill;
    // Rounded like an app icon, so it sits naturally on light and dark backgrounds.
    logo.layer.cornerRadius=8.5;logo.layer.cornerCurve=kCACornerCurveContinuous;logo.clipsToBounds=YES;logo.isAccessibilityElement=NO;[logo.widthAnchor constraintEqualToConstant:36].active=YES;[logo.heightAnchor constraintEqualToConstant:36].active=YES;[brand addArrangedSubview:logo];UILabel *heading=[self label:@"Soovee Commander" size:TARGET_OS_TV?32:22];heading.font=[UIFont boldSystemFontOfSize:TARGET_OS_TV?32:22];[brand addArrangedSubview:heading];UIButton *settings=[self button:@"" action:^{[self showSettings];}];UIButtonConfiguration *gear=settings.configuration;gear.title=nil;gear.image=[UIImage systemImageNamed:@"gearshape"];gear.contentInsets=NSDirectionalEdgeInsetsZero;gear.background.cornerRadius=22;settings.configuration=gear;settings.contentHorizontalAlignment=UIControlContentHorizontalAlignmentCenter;settings.accessibilityLabel=T(@"Settings");[settings.widthAnchor constraintEqualToConstant:44].active=YES;[settings.heightAnchor constraintEqualToConstant:44].active=YES;[brand addArrangedSubview:settings];[root addArrangedSubview:brand];self.brand=brand;
    self.status=[self label:T(@"Starting local transfers…") size:TARGET_OS_TV?21:14];self.status.numberOfLines=1;self.status.textColor=UIColor.secondaryLabelColor;self.status.font=[UIFont systemFontOfSize:12];[root addArrangedSubview:self.status];
    UIStackView *body=[UIStackView new];body.axis=UILayoutConstraintAxisHorizontal;body.spacing=24;[root addArrangedSubview:body];
    if(TARGET_OS_TV){UIStackView *nav=[UIStackView new];nav.axis=UILayoutConstraintAxisVertical;nav.spacing=16;[nav.widthAnchor constraintEqualToConstant:260].active=YES;
        [nav addArrangedSubview:[self button:T(@"Pairing") action:^{[self showPairing];}]];
        [nav addArrangedSubview:[self button:T(@"Files") action:^{self.peer=@"";self.path=@"/";[self showFiles];}]];
        [nav addArrangedSubview:[self button:T(@"Paired devices") action:^{[self showDevices];}]];
        [nav addArrangedSubview:[self button:T(@"Settings") action:^{[self showSettings];}]];
        [nav addArrangedSubview:[UIView new]];[body addArrangedSubview:nav];}
    UIScrollView *scroll=[UIScrollView new];[body addArrangedSubview:scroll];self.scroll=scroll;
    self.content=[UIStackView new];self.content.axis=UILayoutConstraintAxisVertical;self.content.spacing=14;self.content.translatesAutoresizingMaskIntoConstraints=NO;[scroll addSubview:self.content];
    [NSLayoutConstraint activateConstraints:@[[self.content.leadingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.leadingAnchor],[self.content.trailingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.trailingAnchor],[self.content.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor],[self.content.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor],[self.content.widthAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.widthAnchor]]];
    if(!TARGET_OS_TV){self.tabs=[UIStackView new];self.tabs.axis=UILayoutConstraintAxisHorizontal;self.tabs.distribution=UIStackViewDistributionFillEqually;self.tabs.spacing=0;
        NSArray *titles=@[@"Home",@"Files",@"Devices",@"Transfers"],*symbols=@[@"house",@"folder",@"desktopcomputer",@"arrow.left.arrow.right"];
        for(NSInteger i=0;i<4;i++){NSInteger index=i;UIButton *tab=[self button:T(titles[i]) action:^{if(index==0)[self showHome];else if(index==1){self.peer=@"";self.path=@"/";[self.selection removeAllObjects];
#if !TARGET_OS_TV
            self.searchQuery=nil;self.filter=@"";
#endif
            [self showFiles];}else if(index==2)[self showNearby];else [self showTransfers];}];UIButtonConfiguration *cfg=tab.configuration;cfg.image=[UIImage systemImageNamed:symbols[i]];cfg.background.backgroundColor=UIColor.clearColor;cfg.titleAlignment=UIButtonConfigurationTitleAlignmentCenter;tab.contentHorizontalAlignment=UIControlContentHorizontalAlignmentCenter;cfg.imagePlacement=NSDirectionalRectEdgeTop;cfg.imagePadding=6;cfg.contentInsets=NSDirectionalEdgeInsetsMake(10,2,10,2);cfg.titleTextAttributesTransformer=^NSDictionary *(NSDictionary *attributes){NSMutableDictionary *result=[attributes mutableCopy];result[NSFontAttributeName]=[UIFont systemFontOfSize:11 weight:UIFontWeightMedium];return result;};tab.configuration=cfg;[self.tabs addArrangedSubview:tab];}[root addArrangedSubview:self.tabs];
        [self setupFileList:body root:root];[self setupSecondPanel:body];self.sortOrder=[NSUserDefaults.standardUserDefaults integerForKey:@"fileSort"];}
    coreQueue=dispatch_queue_create("Soovee core",DISPATCH_QUEUE_SERIAL);
    NSString *base=NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory,NSUserDomainMask,YES).firstObject;
    NSString *files=NSSearchPathForDirectoriesInDomains(TARGET_OS_TV?NSCachesDirectory:NSDocumentDirectory,NSUserDomainMask,YES).firstObject;
    dispatch_async(coreQueue,^{NSString *error=StartPython();if(error){dispatch_async(dispatch_get_main_queue(),^{[self showError:error];self.status.text=error;});return;}
        NSString *value=CoreCall(@"start",@[[base stringByAppendingPathComponent:@"Soovee"],[files stringByAppendingPathComponent:@"Shared"],UIDevice.currentDevice.name,TARGET_OS_TV?@"tv":@"phone"],YES);
        dispatch_async(dispatch_get_main_queue(),^{[self updateState:value];[self restoreFolders];[self configureFolders:^{[self showHome];}];
            self.timer=[NSTimer scheduledTimerWithTimeInterval:3 repeats:YES block:^(NSTimer *timer){[self call:@"snapshot" args:@[] then:^(NSString *json){[self updateState:json];}];}];});
    });
}
- (void)call:(NSString *)name args:(NSArray *)args then:(void (^)(NSString *))complete {
    dispatch_async(coreQueue,^{NSString *value=CoreCall(name,args,NO);dispatch_async(dispatch_get_main_queue(),^{
        NSData *data=[value dataUsingEncoding:NSUTF8StringEncoding];id object=data?[NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingFragmentsAllowed error:nil]:nil;
        if([object isKindOfClass:NSDictionary.class]&&object[@"error"]){
#if !TARGET_OS_TV
            if(self.progressSheet||self.progressStopped){UIViewController *open=self.progressSheet;self.progressSheet=nil;BOOL stopped=self.progressStopped;self.progressStopped=NO;
                // Stop is not an error: say so briefly; finished files stay.
                void (^report)(void)=^{[self showFiles];if(stopped)[self toast:T(@"Stopped. Finished files stay at the destination.")];else [self showError:object[@"error"]];};
                if(open.presentingViewController)[open dismissViewControllerAnimated:YES completion:report];else report();return;}
#endif
            if(self.operationAlert){UIAlertController *busy=self.operationAlert;self.operationAlert=nil;[busy dismissViewControllerAnimated:YES completion:^{[self showError:object[@"error"]];}];}else [self showError:object[@"error"]];return;}complete(value);
    });});
}
- (void)showError:(NSString *)message {
    self.pairing=NO;if(self.pairingStatus)self.pairingStatus.text=T(@"Connection failed. Check that the other app is open and try again.");
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:T(@"Soovee · Error") message:T(message) preferredStyle:UIAlertControllerStyleAlert];[alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
    if(!self.presentedViewController)[self presentViewController:alert animated:YES completion:nil];
}
- (void)clear:(NSString *)screen { self.screen=screen;NSInteger active=[screen isEqual:@"home"]?0:[screen isEqual:@"files"]?1:([screen isEqual:@"nearby"]||[screen isEqual:@"pair"]||[screen isEqual:@"devices"])?2:[screen isEqual:@"transfers"]?3:-1;for(NSInteger i=0;i<self.tabs.arrangedSubviews.count;i++){UIButton *tab=(UIButton *)self.tabs.arrangedSubviews[i];UIButtonConfiguration *cfg=tab.configuration;cfg.baseForegroundColor=i==active?Accent():UIColor.secondaryLabelColor;tab.configuration=cfg;}for(UIView *view in self.content.arrangedSubviews){[self.content removeArrangedSubview:view];[view removeFromSuperview];}
#if !TARGET_OS_TV
    BOOL files=[screen isEqual:@"files"];self.scroll.hidden=files;self.filesContainer.hidden=!files;
    if(!files){[self.selection removeAllObjects];self.selectionMode=NO;self.searchQuery=nil;[self.view endEditing:YES];}
    [self updateSelectionUI];[self updatePanels];
#endif
}
- (void)updateState:(NSString *)json {
    id value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
    if(![value isKindOfClass:NSDictionary.class])return;
    if(value[@"error"]){[self showError:value[@"error"]];return;}self.state=value;
    if(!self.advertisement&&[value[@"id"] length]){
        self.advertisement=[[NSNetService alloc]initWithDomain:@"local." type:@"_soovee._tcp." name:[@"soovee-" stringByAppendingString:value[@"id"]] port:[value[@"port"] intValue]];
        NSMutableDictionary *txt=[NSMutableDictionary new];for(NSString *key in @[@"id",@"name"]){NSString *text=value[key]?:@"";txt[key]=[text dataUsingEncoding:NSUTF8StringEncoding];}txt[@"kind"]=[(TARGET_OS_TV?@"tv":@"phone") dataUsingEncoding:NSUTF8StringEncoding];txt[@"v"]=[@"1" dataUsingEncoding:NSUTF8StringEncoding];
        [self.advertisement setTXTRecordData:[NSNetService dataFromTXTRecordDictionary:txt]];[self.advertisement publish];
        self.browser=[NSNetServiceBrowser new];self.browser.delegate=self;[self.browser searchForServicesOfType:@"_soovee._tcp." inDomain:@"local."];
    }
    self.status.text=[value[@"localNetwork"] isEqual:@NO]?[NSString stringWithFormat:@"%@ · %@",value[@"name"]?:@"",T(@"Not connected to Wi-Fi: other devices cannot reach this one.")]:[NSString stringWithFormat:@"%@ · %@:%@",value[@"name"]?:@"",value[@"address"]?:@"",value[@"port"]?:@0];
    if(![self.screen isEqual:@"pair"]||!self.code)return;
    NSString *code=value[@"code"]?:@"";self.code.text=code.length==8?[NSString stringWithFormat:@"%@ %@",[code substringToIndex:4],[code substringFromIndex:4]]:T(@"Generate a new code");
    self.endpoint.text=[NSString stringWithFormat:@"%@:%@\n%@ %@ s\n%@",value[@"address"]?:@"",value[@"port"]?:@0,T(@"Code valid for"),value[@"expires"]?:@0,T(@"Keep this app open during transfers.")];
    NSArray *matrix=value[@"qr"];if(!matrix.count){self.qr.image=nil;return;}
    NSUInteger size=matrix.count;UIGraphicsBeginImageContextWithOptions(CGSizeMake(size,size),NO,1);
    [UIColor.whiteColor setFill];UIRectFill(CGRectMake(0,0,size,size));[UIColor.blackColor setFill];
    for(NSUInteger y=0;y<size;y++)for(NSUInteger x=0;x<size;x++)if([matrix[y][x] boolValue])UIRectFill(CGRectMake(x,y,1,1));
    self.qr.image=UIGraphicsGetImageFromCurrentImageContext();UIGraphicsEndImageContext();
}
- (void)netServiceBrowser:(NSNetServiceBrowser *)browser didFindService:(NSNetService *)service moreComing:(BOOL)more {
    if(self.services.count>=256)return;[self.services addObject:service];service.delegate=self;[service resolveWithTimeout:5];
}
- (void)netServiceBrowser:(NSNetServiceBrowser *)browser didRemoveService:(NSNetService *)service moreComing:(BOOL)more {
    [self.services removeObject:service];[self.nearby removeObjectForKey:service.name];if([self.screen isEqual:@"nearby"])[self showNearby];
}
- (void)netServiceDidResolveAddress:(NSNetService *)service {
    NSDictionary *raw=[NSNetService dictionaryFromTXTRecordData:service.TXTRecordData];NSString *(^text)(NSString *)=^NSString *(NSString *key){return [[NSString alloc]initWithData:raw[key]?:NSData.data encoding:NSUTF8StringEncoding]?:@"";};
    NSString *identity=text(@"id"),*name=text(@"name");if(identity.length!=32||[identity isEqual:self.state[@"id"]]||name.length<1||name.length>80||![text(@"v") isEqual:@"1"])return;
    if([identity rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location!=NSNotFound||[name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound)return;
    for(NSData *address in service.addresses){if(address.length<sizeof(struct sockaddr_in))continue;const struct sockaddr_in *socket=address.bytes;if(socket->sin_family!=AF_INET)continue;char host[INET_ADDRSTRLEN];if(!inet_ntop(AF_INET,&socket->sin_addr,host,sizeof(host)))continue;
        self.nearby[service.name]=@{@"id":identity,@"name":name,@"kind":text(@"kind"),@"host":[NSString stringWithUTF8String:host],@"port":@(service.port)};if([self.screen isEqual:@"nearby"])[self showNearby];return;}
}
- (void)connectInvitation:(NSString *)invitation { [self beginPairing:invitation host:@"" port:@0 code:@""]; }
- (NSString *)deviceSymbol:(NSString *)kind { return [kind isEqual:@"tv"]?@"tv":[kind isEqual:@"phone"]?@"iphone":@"desktopcomputer"; }
- (void)scanQR {
#if !TARGET_OS_TV
    SooveeQRScanner *scanner=[SooveeQRScanner new];scanner.modalPresentationStyle=UIModalPresentationFullScreen;scanner.result=^(NSString *value){[self connectInvitation:value];};[self presentViewController:scanner animated:YES completion:nil];
#endif
}
// Devices: paired devices first (open, or remove from their menu), then devices nearby to pair, then other ways to add one.
- (void)showNearby {
    [self clear:@"nearby"];[self screenTitle:T(@"Devices") back:nil action:nil];
    NSMutableDictionary *found=[NSMutableDictionary new];for(NSDictionary *device in self.nearby.allValues)found[device[@"id"]]=device;
    NSMutableArray *paired=[NSMutableArray new];NSMutableSet *pairedIds=[NSMutableSet new];
    for(NSDictionary *peer in self.state[@"peers"]){NSString *identity=peer[@"id"];[pairedIds addObject:identity];NSDictionary *near=found[identity];
        UIAction *remove=[UIAction actionWithTitle:T(@"Remove pairing") image:[UIImage systemImageNamed:@"trash"] identifier:nil handler:^(UIAction *a){[self removePairing:identity name:peer[@"name"]];}];remove.attributes=UIMenuElementAttributesDestructive;
        UIMenu *menu=[UIMenu menuWithTitle:peer[@"name"] children:@[
            [UIAction actionWithTitle:T(@"Open") image:[UIImage systemImageNamed:@"folder"] identifier:nil handler:^(UIAction *a){[self openPaired:peer near:near];}],remove]];
        UIView *row=[self row:peer[@"name"] detail:T(near?@"On this network":@"Not found on this network") symbol:[self deviceSymbol:near[@"kind"]] tint:near?UIColor.systemGreenColor:UIColor.systemGrayColor value:nil chevron:YES menu:nil action:^{[self openPaired:peer near:near];}];
        // A trailing "…" button keeps Remove one tap away.
        UIButton *more=[UIButton buttonWithType:UIButtonTypeSystem];[more setImage:[UIImage systemImageNamed:@"ellipsis.circle"] forState:UIControlStateNormal];more.tintColor=Accent();more.menu=menu;more.showsMenuAsPrimaryAction=YES;more.accessibilityLabel=[NSString stringWithFormat:T(@"More for %@"),peer[@"name"]];
        [more.widthAnchor constraintEqualToConstant:44].active=YES;
        UIStackView *line=[UIStackView new];line.axis=UILayoutConstraintAxisHorizontal;line.alignment=UIStackViewAlignmentCenter;[line addArrangedSubview:row];[line addArrangedSubview:more];
        [paired addObject:line];}
    [self section:T(@"Paired devices") rows:paired footer:paired.count?T(@"Tap a device to browse its shared folders. Use … to remove a pairing."):T(@"No paired devices yet. Pair one below.")];
    NSMutableArray *nearby=[NSMutableArray new];
    NSArray *devices=[[found allValues] sortedArrayUsingDescriptors:@[[NSSortDescriptor sortDescriptorWithKey:@"name" ascending:YES selector:@selector(localizedCaseInsensitiveCompare:)]]];
    for(NSDictionary *device in devices){if([pairedIds containsObject:device[@"id"]])continue;
        [nearby addObject:[self row:device[@"name"] detail:T(@"Tap to pair") symbol:[self deviceSymbol:device[@"kind"]] tint:Accent() value:T(@"Pair") chevron:NO menu:nil action:^{[self requestCode:device retry:YES];}]];}
    if(!nearby.count){UIView *row=[self row:T(@"Looking for devices…") detail:nil symbol:nil tint:nil value:nil chevron:NO menu:nil action:nil];
        UIActivityIndicatorView *spinner=[[UIActivityIndicatorView alloc]initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];[spinner startAnimating];spinner.translatesAutoresizingMaskIntoConstraints=NO;[row addSubview:spinner];
        [NSLayoutConstraint activateConstraints:@[[spinner.trailingAnchor constraintEqualToAnchor:row.trailingAnchor constant:-16],[spinner.centerYAnchor constraintEqualToAnchor:row.centerYAnchor]]];[nearby addObject:row];}
    [self section:T(@"Nearby") rows:nearby footer:T(@"The other device shows a code after you tap it. Both devices need Soovee open and the same Wi-Fi.")];
    NSMutableArray *add=[NSMutableArray new];
#if !TARGET_OS_TV
    [add addObject:[self row:T(@"Scan QR code") detail:nil symbol:@"qrcode.viewfinder" tint:UIColor.systemBlueColor action:^{[self scanQR];}]];
#endif
    [add addObject:[self row:T(@"Show this iPhone’s code") detail:T(@"For pairing started on the other device") symbol:@"number" tint:UIColor.systemIndigoColor action:^{[self showPairing];}]];
#if !TARGET_OS_TV
    [add addObject:[self row:T(@"Paste invitation") detail:nil symbol:@"link" tint:UIColor.systemTealColor action:^{[self join];}]];
#endif
    NSString *me=self.state[@"name"]?[NSString stringWithFormat:@"%@ · %@",self.state[@"name"],[self.state[@"localNetwork"] boolValue]?self.state[@"address"]:T(@"not connected to Wi-Fi")]:@"";
    [self section:T(@"Add a device") rows:add footer:me];
}
- (void)openPaired:(NSDictionary *)peer near:(NSDictionary *)near {
    if([self.state[@"role"] isEqual:@"controlled"]){[self showError:T(@"Enable both directions in Device role first.")];return;}
    if(near){[self call:@"reconnect" args:@[peer[@"id"],near[@"host"],near[@"port"]] then:^(NSString *json){[self updateState:json];[self openDevice:peer[@"id"]];}];return;}
    [self openDevice:peer[@"id"]];
}
- (void)requestCode:(NSDictionary *)device retry:(BOOL)retry {
    [self call:@"request_pairing" args:@[device[@"host"],device[@"port"]] then:^(NSString *json){NSDictionary *answer=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];BOOL asked=[answer[@"asked"] boolValue];
        if(!asked&&retry){
            // The device may have restarted on another address or port: look it up again once.
            for(NSNetService *service in self.services)[service resolveWithTimeout:3];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(2*NSEC_PER_SEC)),dispatch_get_main_queue(),^{NSDictionary *fresh=device;
                for(NSDictionary *value in self.nearby.allValues)if([value[@"id"] isEqual:device[@"id"]])fresh=value;
                [self requestCode:fresh retry:NO];});
            return;}
        [self askCode:device asked:asked];}];
}
- (void)askCode:(NSDictionary *)device asked:(BOOL)asked {
    NSString *message=asked?T(@"The device now shows a pairing code. Type it here, or scan its QR."):T(@"Open Soovee on the device and type the pairing code it shows, or scan its QR.");
    UIAlertController *pin=[UIAlertController alertControllerWithTitle:device[@"name"] message:message preferredStyle:UIAlertControllerStyleAlert];[pin addTextFieldWithConfigurationHandler:^(UITextField *field){field.placeholder=T(@"Eight-digit code");field.keyboardType=UIKeyboardTypeNumberPad;}];
    UIAlertAction *pair=[UIAlertAction actionWithTitle:T(@"Pair") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self beginPairing:@"" host:device[@"host"] port:device[@"port"] code:pin.textFields.firstObject.text?:@""];}];
    // Pair becomes available only once all eight digits are typed.
    pair.enabled=NO;[pin.textFields.firstObject addAction:[UIAction actionWithHandler:^(UIAction *a){NSString *digits=[[pin.textFields.firstObject.text componentsSeparatedByCharactersInSet:NSCharacterSet.decimalDigitCharacterSet.invertedSet] componentsJoinedByString:@""];pair.enabled=digits.length==8;}] forControlEvents:UIControlEventEditingChanged];
    pin.textFields.firstObject.textContentType=UITextContentTypeOneTimeCode;[pin addAction:pair];pin.preferredAction=pair;
#if !TARGET_OS_TV
    [pin addAction:[UIAlertAction actionWithTitle:T(@"Scan QR instead") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){SooveeQRScanner *scanner=[SooveeQRScanner new];scanner.modalPresentationStyle=UIModalPresentationFullScreen;scanner.result=^(NSString *value){[self connectInvitation:value];};[self presentViewController:scanner animated:YES completion:nil];}]];
#endif
    [pin addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:pin animated:YES completion:nil];
}
- (void)showPairingRequest:(NSString *)name {
    // Another device asked for our code: show it without any tapping here.
    if(self.presentedViewController)[self dismissViewControllerAnimated:NO completion:nil];
    [self call:@"snapshot" args:@[] then:^(NSString *json){[self updateState:json];[self showPairing];
        UILabel *who=[self label:[NSString stringWithFormat:T(@"%@ wants to pair. Type this code there, or scan the QR."),name?:@""] size:TARGET_OS_TV?26:19];who.textColor=Accent();[self.content insertArrangedSubview:who atIndex:1];}];
}
- (void)removePairing:(NSString *)identity name:(NSString *)name { [self removePairing:identity name:name pairAgain:NO]; }
- (void)removePairing:(NSString *)identity name:(NSString *)name pairAgain:(BOOL)again {
    UIAlertController *ask=[UIAlertController alertControllerWithTitle:[NSString stringWithFormat:T(@"Remove %@? Files on both devices stay. To connect again, pair with a new code."),name?:@""] message:nil preferredStyle:TARGET_OS_TV?UIAlertControllerStyleAlert:UIAlertControllerStyleActionSheet];
    ask.popoverPresentationController.sourceView=self.view;ask.popoverPresentationController.sourceRect=CGRectMake(CGRectGetMidX(self.view.bounds),CGRectGetMidY(self.view.bounds),1,1);ask.popoverPresentationController.permittedArrowDirections=0;
    [ask addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    [ask addAction:[UIAlertAction actionWithTitle:T(@"Remove pairing") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){[self call:@"remove_pairing" args:@[identity] then:^(NSString *json){[self updateState:json];[self showNearby];
        if(!again)return;
        // Pair again right away: the device shows its new code and only the code is typed here.
        NSDictionary *found=nil;for(NSDictionary *device in self.nearby.allValues)if([device[@"id"] isEqual:identity])found=device;
        if(found)[self requestCode:found retry:YES];}];}]];
    [self presentViewController:ask animated:YES completion:nil];
}
- (void)showPairing {
    [self clear:@"pair"];self.peer=@"";self.path=@"/";
    if(TARGET_OS_TV)[self.content addArrangedSubview:[self label:T(@"Connect your devices") size:32]];
    else [self screenTitle:T(@"This iPhone’s code") back:T(@"Devices") action:^{[self showNearby];}];
    [self.content addArrangedSubview:[self textLabel:T(@"On the other device, choose this iPhone and type the code, or scan the QR in Soovee.") style:UIFontTextStyleBody weight:UIFontWeightRegular color:UIColor.secondaryLabelColor]];
    UIStackView *card=[UIStackView new];card.axis=TARGET_OS_TV?UILayoutConstraintAxisHorizontal:UILayoutConstraintAxisVertical;card.spacing=24;card.alignment=UIStackViewAlignmentCenter;
    self.qr=[UIImageView new];self.qr.backgroundColor=UIColor.whiteColor;self.qr.contentMode=UIViewContentModeScaleAspectFit;self.qr.layer.magnificationFilter=kCAFilterNearest;
    [NSLayoutConstraint activateConstraints:@[[self.qr.widthAnchor constraintEqualToConstant:TARGET_OS_TV?360:250],[self.qr.heightAnchor constraintEqualToAnchor:self.qr.widthAnchor]]];[card addArrangedSubview:self.qr];
    UIStackView *text=[UIStackView new];text.axis=UILayoutConstraintAxisVertical;text.spacing=16;
    self.code=[self label:@"" size:TARGET_OS_TV?55:36];self.code.font=[UIFont monospacedDigitSystemFontOfSize:TARGET_OS_TV?55:36 weight:UIFontWeightBold];[text addArrangedSubview:self.code];
    self.endpoint=[self label:@"" size:TARGET_OS_TV?24:16];[text addArrangedSubview:self.endpoint];
    [text addArrangedSubview:[self button:T(@"Generate new code") action:^{[self call:@"renew" args:@[] then:^(NSString *value){[self updateState:value];}];}]];
#if !TARGET_OS_TV
    [text addArrangedSubview:[self button:T(@"Copy pairing invitation") action:^{UIPasteboard.generalPasteboard.string=self.state[@"invitation"];}]];
#endif
    [card addArrangedSubview:text];[self.content addArrangedSubview:card];
    [self updateState:[[NSString alloc] initWithData:[NSJSONSerialization dataWithJSONObject:self.state options:0 error:nil] encoding:NSUTF8StringEncoding]];
}
- (void)showDevices { [self showNearby]; }
- (void)showFiles {
    self.shownCount=0;NSString *peer=self.peer,*path=self.path;
#if TARGET_OS_TV
    [self clear:@"files"];[self.content addArrangedSubview:[self label:T(@"Loading files…") size:18]];
#else
    if(self.searchQuery&&!peer.length){[self deepSearch:self.searchQuery];return;}   // refresh the results, not the folder
    [self.selection removeAllObjects];self.selectionMode=NO;self.fileEntries=@[];[self showFilesLoading];
#endif
    [self call:peer.length?@"browse":@"browse_local_path" args:peer.length?@[peer,path]:@[path] then:^(NSString *json){if(![self.screen isEqual:@"files"]||![self.path isEqual:path]||![self.peer isEqual:peer])return;id values=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];self.fileEntries=[values isKindOfClass:NSArray.class]?values:@[];
#if TARGET_OS_TV
        [self renderFiles];
#else
        // Local folders also need their real location for thumbnails, preview and sharing.
        if(![path isEqual:@"/"])[self rememberPlace:@"recentFolders" path:path name:path.lastPathComponent];
        if(peer.length||[path isEqual:@"/"]){self.filesBase=nil;[self renderFiles];return;}
        [self call:@"local_file" args:@[path] then:^(NSString *base){if(![self.path isEqual:path]||![self.screen isEqual:@"files"])return;self.filesBase=base;[self renderFiles];}];
#endif
    }];
}
- (void)localFile:(NSString *)path name:(NSString *)name {
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:name message:nil preferredStyle:UIAlertControllerStyleAlert];
#if !TARGET_OS_TV
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Open") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){
        NSURL *url=[NSURL fileURLWithPath:[self.state[@"folder"] stringByAppendingPathComponent:[path hasPrefix:@"/"]?[path substringFromIndex:1]:path]];
        self.document=[UIDocumentInteractionController interactionControllerWithURL:url];self.document.delegate=self;[self.document presentPreviewAnimated:YES];
    }]];
#endif
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Delete") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){
        UIAlertController *confirm=[UIAlertController alertControllerWithTitle:name message:T(@"Delete this item?") preferredStyle:UIAlertControllerStyleAlert];[confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[confirm addAction:[UIAlertAction actionWithTitle:T(@"Delete") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *value){[self call:@"delete_local" args:@[path] then:^(NSString *json){[self showFiles];}];}]];[self presentViewController:confirm animated:YES completion:nil];
    }]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:alert animated:YES completion:nil];
}
- (void)join {
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:T(@"Pair device") message:T(@"Paste Soovee invitation") preferredStyle:UIAlertControllerStyleAlert];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field){field.placeholder=T(@"Paste Soovee invitation");field.autocorrectionType=UITextAutocorrectionTypeNo;}];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    [alert addAction:[UIAlertAction actionWithTitle:T(@"Pair") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){NSString *text=alert.textFields.firstObject.text?:@"";[self call:@"pair" args:@[text,@"",@"0",@""] then:^(NSString *json){[self updateState:json];[self showPairing];}];}]];[self presentViewController:alert animated:YES completion:nil];
}
- (void)showSettings {
    [self clear:@"settings"];[self screenTitle:T(@"Settings") back:nil action:nil];
#if !TARGET_OS_TV
    NSArray *styles=@[@"System",@"Light",@"Dark"];NSInteger current=[NSUserDefaults.standardUserDefaults objectForKey:@"appearance"]?[NSUserDefaults.standardUserDefaults integerForKey:@"appearance"]:UIUserInterfaceStyleDark;
    NSMutableArray *choices=[NSMutableArray new];for(NSInteger i=0;i<3;i++){NSInteger style=i;UIAction *choice=[UIAction actionWithTitle:T(styles[i]) image:nil identifier:nil handler:^(UIAction *a){[NSUserDefaults.standardUserDefaults setInteger:style forKey:@"appearance"];self.overrideUserInterfaceStyle=style;[self showSettings];}];if(i==current)choice.state=UIMenuElementStateOn;[choices addObject:choice];}
    [self section:T(@"Appearance") rows:@[[self row:T(@"Theme") detail:nil symbol:@"circle.lefthalf.filled" tint:UIColor.systemIndigoColor value:T(styles[MIN(MAX(current,0),2)]) chevron:NO menu:[UIMenu menuWithChildren:choices] action:nil]] footer:nil];
    [self section:T(@"Files") rows:@[
        [self row:T(@"Folder access and sharing") detail:T(@"Folders from Files and what paired devices may see") symbol:@"folder.badge.person.crop" tint:UIColor.systemBlueColor action:^{[self manageFolders];}],
        [self row:T(@"Import files into shared folder…") detail:nil symbol:@"square.and.arrow.down" tint:UIColor.systemTealColor action:^{UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc] initForOpeningContentTypes:@[UTTypeData] asCopy:YES];picker.allowsMultipleSelection=YES;picker.delegate=self;[self presentViewController:picker animated:YES completion:nil];}]] footer:nil];
#endif
    BOOL controlled=[self.state[@"role"] isEqual:@"controlled"];NSMutableArray *roles=[NSMutableArray new];
    for(NSArray *value in @[@[@"Both directions",@"both"],@[@"Controlled device",@"controlled"]]){UIAction *choice=[UIAction actionWithTitle:T(value[0]) image:nil identifier:nil handler:^(UIAction *a){[self call:@"set_role" args:@[value[1]] then:^(NSString *json){[self updateState:json];[self showSettings];}];}];if([value[1] isEqual:controlled?@"controlled":@"both"])choice.state=UIMenuElementStateOn;[roles addObject:choice];}
    [self section:T(@"Transfers") rows:@[
        [self row:T(@"Device role") detail:nil symbol:@"arrow.left.arrow.right" tint:UIColor.systemOrangeColor value:T(controlled?@"Controlled device":@"Both directions") chevron:NO menu:[UIMenu menuWithChildren:roles] action:nil],
        [self row:T(@"Devices") detail:nil symbol:@"desktopcomputer" tint:UIColor.systemGreenColor action:^{[self showNearby];}]]
        footer:T(controlled?@"Other devices can use folders shared from this iPhone, but this iPhone cannot open theirs.":@"This iPhone can open folders shared by paired devices, and they can open folders you share.")];
    NSString *version=NSBundle.mainBundle.infoDictionary[@"CFBundleShortVersionString"]?:@"";
    [self section:T(@"Support") rows:@[
        [self row:T(@"Diagnostic log") detail:T(@"Errors and events, for troubleshooting") symbol:@"doc.text.magnifyingglass" tint:UIColor.systemGrayColor action:^{[self showLog];}],
        [self row:T(@"About") detail:nil symbol:@"info.circle" tint:UIColor.systemGrayColor value:version chevron:YES menu:nil action:^{UIAlertController *alert=[UIAlertController alertControllerWithTitle:[@"Soovee Commander " stringByAppendingString:version] message:@"MIT · CPython PSF · OpenSSL Apache-2.0 · SPAKE2 MIT · qrcode BSD-3-Clause" preferredStyle:UIAlertControllerStyleAlert];[alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];[self presentViewController:alert animated:YES completion:nil];}]] footer:nil];
}
#include "GroupedList.inc"
#include "FileList.inc"
#include "Preview.inc"
#include "Overview.inc"
#include "SecondPanel.inc"
#include "Progress.inc"
#include "PhoneLibrary.inc"
#include "DeviceConnection.inc"

#if !TARGET_OS_TV
- (UIViewController *)documentInteractionControllerViewControllerForPreview:(UIDocumentInteractionController *)controller {return self;}
- (void)documentPicker:(UIDocumentPickerViewController *)picker didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    if(self.choosingFolder){self.choosingFolder=NO;for(NSURL *url in urls)[self retainFolder:url];return;}
    dispatch_async(coreQueue,^{NSString *failure=nil;
        for(NSURL *url in urls){BOOL access=[url startAccessingSecurityScopedResource];NSError *error=nil;
            NSFileHandle *handle=[NSFileHandle fileHandleForReadingFromURL:url error:&error];
            if(handle){NSString *value=CoreCall(@"import_file",@[url.lastPathComponent,@(handle.fileDescriptor)],NO);[handle closeFile];
                id result=[NSJSONSerialization JSONObjectWithData:[value dataUsingEncoding:NSUTF8StringEncoding] options:NSJSONReadingFragmentsAllowed error:nil];
                if([result isKindOfClass:NSDictionary.class])failure=result[@"error"];
            }else failure=error.localizedDescription?:@"Could not read the selected file";
            if(access)[url stopAccessingSecurityScopedResource];if(failure)break;
        }
        dispatch_async(dispatch_get_main_queue(),^{if(failure){[self showError:failure];return;}self.peer=@"";self.path=@"/";[self showFiles];});
    });
}
#endif
@end

@interface SooveeSceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(nonatomic,strong) UIWindow *window;
@end
@implementation SooveeSceneDelegate
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    self.window=[[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];self.window.rootViewController=[SooveeViewController new];[self.window makeKeyAndVisible];
}
@end
@interface SooveeAppDelegate : UIResponder <UIApplicationDelegate>
@end
@implementation SooveeAppDelegate
- (UISceneConfiguration *)application:(UIApplication *)application configurationForConnectingSceneSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    UISceneConfiguration *config=[[UISceneConfiguration alloc] initWithName:@"Soovee" sessionRole:session.role];config.delegateClass=SooveeSceneDelegate.class;return config;
}
@end
int main(int argc,char **argv){@autoreleasepool{return UIApplicationMain(argc,argv,nil,NSStringFromClass(SooveeAppDelegate.class));}}
